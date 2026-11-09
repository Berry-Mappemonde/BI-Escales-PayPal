"""LLM cascade for the Escales captain.

Order, to spare Nebius credits: NVIDIA NIM, the smaller NIM fallback,
OpenRouter, Anthropic, then Nebius Token Factory, then the deterministic
rules in the captain.

Each provider runs only when its API key is set. The master flag
``ESCALES_LLM_ENABLED`` is off by default: ``has_llm()`` is false and no
HTTP call is made. Nebius stays implemented but stays off unless
``ESCALES_LLM_NEBIUS_ENABLED`` is truthy, and even then it is the last
resort before the rules.

The captain proposes. This module never captures, voids, or moves money.

A daily call cap applies only when ``ESCALES_ENV=production`` (or when
``ESCALES_RATE_LIMIT_ENABLED`` forces it). Development does not count calls.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import re
import time
from typing import Any, Awaitable, Callable, Optional

import httpx

from app.core.tracing import annotate_run, traced
from app.escales.app_i18n import normalize_app_lang

log = logging.getLogger("escales.llm")

_SECRET_VALUE = re.compile(
    r"(?i)\b(?:api[_ -]?key|client[_ -]?secret|secret|password|mongo_url)"
    r"\b\s*[:=]\s*\S+"
)
_BEARER = re.compile(r"(?i)\bbearer\s+\S+")
# Prefixes are split so the source file does not contain a live-looking key.
_VENDOR_KEY = re.compile(
    "(?i)(?:" + "nvapi" + r"-" + r"[A-Za-z0-9._\-]+|" + "sk" + r"-" + r"[A-Za-z0-9._\-]+)"
)
_MONGO_URL = re.compile(r"mongodb(?:\+srv)?://\S+")


def safe_error_message(exc: BaseException) -> str:
    """Exception text safe to log. Secrets and connection strings are removed."""
    message = " ".join(str(exc).split())
    message = _BEARER.sub("bearer [redacted]", message)
    message = _SECRET_VALUE.sub("[redacted]", message)
    message = _VENDOR_KEY.sub("[redacted]", message)
    message = _MONGO_URL.sub("[redacted]", message)
    return message[:400] or type(exc).__name__

# HTTP hops, then the local rules applied by the captain when nothing answered.
# NIM primary, then the smaller NIM fallback, then the other providers.
CASCADE = ("nim", "nim_fallback", "openrouter", "anthropic", "tokenfactory", "rules")
HTTP_CASCADE = ("nim", "nim_fallback", "openrouter", "anthropic", "tokenfactory")
# JSON advisory only. Chat and reports stay on Super first.
JSON_HTTP_CASCADE = ("nim_fallback", "nim", "openrouter", "anthropic", "tokenfactory")

NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
TOKENFACTORY_DEFAULT_BASE = "https://api.tokenfactory.nebius.com/v1"

# Benchmarked NIM defaults (final.log). Env overrides still win.
# NIM_TEMPERATURE stays unset so chat 0.3, reports 0.2 and JSON 0 apply.
# The old id nvidia/nemotron-3.5-super-vl-120b-a12b returns 404.
# So does nvidia/nemotron-3.5-super-120b-a12b without the private/ prefix.
# NIM_MODEL on Render (sync: false) overrides this default. Those two ids,
# and the lightning id used as the primary, are refused so the hop still
# sends the private Super id. model_source.model is the model that answered.
# model_source.reason names the hop and the failure kind, never a secret.
NIM_MODEL_DEFAULT = "private/nvidia/nemotron-3.5-super-120b-a12b"
NIM_FALLBACK_MODEL_DEFAULT = "nvidia/nemotron-3.5-lightning-30b-a3b"
# A primary id is private/nvidia/<model>, <provider>/<org>/<model>, or a
# two-part catalog id such as nvidia/<model>. A glued copy is refused.
_NIM_ID_PIECE = r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}"
_NIM_ID_RE = re.compile(
    rf"^(?:private/nvidia/{_NIM_ID_PIECE}"
    rf"|{_NIM_ID_PIECE}/{_NIM_ID_PIECE}/{_NIM_ID_PIECE}"
    rf"|{_NIM_ID_PIECE}/{_NIM_ID_PIECE})$"
)
# Ids that must not be the primary hop. The value is the public reason.
_NIM_REJECTED_IDS = {
    "nvidia/nemotron-3.5-super-vl-120b-a12b": "returns HTTP 404 at NVIDIA",
    "nvidia/nemotron-3.5-super-120b-a12b": "returns HTTP 404 at NVIDIA without the private/ prefix",
    "nvidia/nemotron-3.5-lightning-30b-a3b": "is the lightning fallback, not the Super model",
}
NIM_MAX_TOKENS_DEFAULT = 400
NIM_TOP_P_DEFAULT = 0.95
NIM_REASONING_DEFAULT = "none"
NIM_EXTRA_BODY_DEFAULT = {"chat_template_kwargs": {"enable_thinking": False}}
NIM_TIMEOUT_S = 20.0
NIM_FALLBACK_TIMEOUT_S = 10.0
# A 404 or 403 means this key cannot use that hop. Skip it for ten minutes.
HOP_BLOCK_S = 600.0
RETRY_AFTER_CAP_S = 3.0
# Attribute kept so a script can still assign llm.NIM_MODEL. Env wins.
NIM_MODEL = NIM_MODEL_DEFAULT

# Free router. A paid id is used only when OPENROUTER_MODEL sets one.
OPENROUTER_DEFAULT_MODEL = "openrouter/free"
OPENROUTER_REFERER = "https://github.com/Berry-Mappemonde/BI-Escales-PayPal"
OPENROUTER_TITLE = "BI Escales"
ANTHROPIC_MODEL = "claude-haiku-4-5"
TOKENFACTORY_MODEL = "nvidia/Nemotron-3.5-Super-VL"

# Each provider call, not the whole cascade. Default sits in the 8–10 s band.
DEFAULT_PROVIDER_TIMEOUT_S = 10.0
TIMEOUT = httpx.Timeout(DEFAULT_PROVIDER_TIMEOUT_S, connect=8.0)
_TIMEOUT_ENV = {
    "nim": "ESCALES_LLM_TIMEOUT_NIM_S",
    "nim_fallback": "ESCALES_LLM_TIMEOUT_NIM_FALLBACK_S",
    "openrouter": "ESCALES_LLM_TIMEOUT_OPENROUTER_S",
    "anthropic": "ESCALES_LLM_TIMEOUT_ANTHROPIC_S",
    "tokenfactory": "ESCALES_LLM_TIMEOUT_TOKENFACTORY_S",
}
_TRUTHY = {"1", "true", "yes", "on"}
_THINK_TAG = "think"
_THINK_OPEN_MARK = "<" + _THINK_TAG
_THINK_CLOSE_MARK = "</" + _THINK_TAG + ">"
_THINK_BLOCK_RE = re.compile(
    re.escape(_THINK_OPEN_MARK) + r"\b[^>]*>.*?" + re.escape(_THINK_CLOSE_MARK),
    re.IGNORECASE | re.DOTALL,
)
_THINK_OPEN_RE = re.compile(
    re.escape(_THINK_OPEN_MARK) + r"\b[^>]*>.*\Z",
    re.IGNORECASE | re.DOTALL,
)

_DEFAULT_SYSTEM = (
    "You are the Blue Intelligence Escales captain. "
    "You propose only. You never capture, void, or move money."
)
_DEFAULT_SYSTEM_FR = (
    "Tu es le capitaine Escales de Blue Intelligence. "
    "Tu proposes seulement. Tu n'encaisses, n'annules ni ne déplaces d'argent."
)


def default_system(lang: Optional[str] = None) -> str:
    if normalize_app_lang(lang) == "fr":
        return _DEFAULT_SYSTEM_FR
    return _DEFAULT_SYSTEM


def default_json_system(lang: Optional[str] = None) -> str:
    if normalize_app_lang(lang) == "fr":
        return "Réponds par un seul objet JSON. Pas de fence markdown ni de commentaire."
    return "Reply with one JSON object only. No markdown fence and no commentary."

_Caller = Callable[..., Awaitable["LlmResult"]]


class LlmResult:
    """Model text plus the provider and model id that produced it.

    ``reason`` is a short cause when the hop is not the configured primary
    success. It names model ids and failure kinds only, never a secret.
    """

    def __init__(
        self,
        text: str,
        provider: str,
        model: str,
        reason: str = "",
        fallback_reason: Optional[dict[str, str]] = None,
    ) -> None:
        self.text = text
        self.provider = provider
        self.model = model
        self.reason = reason
        self.fallback_reason = {
            str(key): str(value)
            for key, value in (fallback_reason or {}).items()
            if str(key).strip() and str(value).strip()
        }

    def __bool__(self) -> bool:
        return bool(self.text)

    def __repr__(self) -> str:
        return f"LlmResult(provider={self.provider!r}, model={self.model!r}, text={self.text!r})"


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _truthy(name: str) -> bool:
    return _env(name).lower() in _TRUTHY


def llm_enabled() -> bool:
    """Master switch. Off unless ``ESCALES_LLM_ENABLED`` is truthy."""
    return _truthy("ESCALES_LLM_ENABLED")


def nebius_enabled() -> bool:
    """Nebius is off unless ``ESCALES_LLM_NEBIUS_ENABLED`` is truthy."""
    return _truthy("ESCALES_LLM_NEBIUS_ENABLED")


def nvidia_key() -> str:
    return _env("NVIDIA_API_KEY")


def openrouter_key() -> str:
    return _env("OPENROUTER_API_KEY")


def anthropic_key() -> str:
    return _env("ANTHROPIC_API_KEY")


def nebius_key() -> str:
    return _env("NEBIUS_API_KEY")


def openrouter_model() -> str:
    return _env("OPENROUTER_MODEL") or OPENROUTER_DEFAULT_MODEL


def _env_float(raw: str, default: float) -> float:
    try:
        value = float(raw.replace(",", "."))
    except (TypeError, ValueError):
        return default
    if value != value:  # NaN
        return default
    return value


_nim_404_fallbacks = 0


def nim_404_fallback_count() -> int:
    """How many times the primary NIM id answered 404 and the cascade moved on."""
    return _nim_404_fallbacks


def reset_nim_404_fallbacks() -> None:
    global _nim_404_fallbacks
    _nim_404_fallbacks = 0


_nim_model_reason = ""
_nim_model_fallback: dict[str, str] = {}


def reset_nim_model_choice() -> None:
    """Forget a previous ``NIM_MODEL`` refusal. The next ``nim_model()`` reads the env again."""
    global _nim_model_reason, _nim_model_fallback
    _nim_model_reason = ""
    _nim_model_fallback = {}


def nim_model_reason() -> str:
    """Why the primary id is not the raw ``NIM_MODEL`` value. Empty when it is used as set."""
    return _nim_model_reason


def nim_model_fallback_reason() -> dict[str, str]:
    """Public reason when ``NIM_MODEL`` was refused before the call. No secret."""
    return dict(_nim_model_fallback)


def _nim_duplicated_fragment(value: str) -> bool:
    parts = [part for part in (value or "").split("/") if part]
    folded = [part.casefold() for part in parts]
    if len(folded) != len(set(folded)):
        return True
    low = (value or "").casefold()
    return any(len(part) >= 12 and low.count(part) > 1 for part in folded)


def _nim_id_problem(value: str) -> str:
    """Empty when the id is a single well-formed model id."""
    if _nim_duplicated_fragment(value) or not _NIM_ID_RE.fullmatch(value or ""):
        if _nim_duplicated_fragment(value):
            return "malformed model id: duplicated fragment"
        return "malformed model id"
    return ""


def nim_model() -> str:
    """Primary NIM id. ``NIM_MODEL`` env, else the module attribute, else the benchmarked default.

    A known 404 id, the lightning id placed in ``NIM_MODEL``, or a malformed
    id (wrong shape, or a fragment repeated) is not sent. The private Super
    id is sent instead. ``nim_model_reason`` and ``nim_model_fallback_reason``
    say so. A well-formed catalog id is sent as set.
    """
    global _nim_model_reason, _nim_model_fallback
    configured = _env("NIM_MODEL")
    chosen = configured or (NIM_MODEL or "").strip() or NIM_MODEL_DEFAULT
    problem = _nim_id_problem(chosen)
    if problem:
        _nim_model_reason = (
            f"NIM_MODEL is malformed ({problem}). "
            f"The primary hop sends {NIM_MODEL_DEFAULT}. "
            "Set NIM_MODEL to private/nvidia/<model> or <provider>/<org>/<model>."
        )
        _nim_model_fallback = {"nim": problem}
        return NIM_MODEL_DEFAULT
    why = _NIM_REJECTED_IDS.get(chosen)
    if why:
        _nim_model_reason = (
            f"NIM_MODEL is {chosen}, which {why}. "
            f"The primary hop sends {NIM_MODEL_DEFAULT}. "
            "On Render, set NIM_MODEL to that id or unset it."
        )
        _nim_model_fallback = {}
        return NIM_MODEL_DEFAULT
    _nim_model_reason = ""
    _nim_model_fallback = {}
    return chosen


def nim_fallback_model() -> str:
    """Second NIM id. Empty ``NIM_FALLBACK_MODEL`` disables the step."""
    if "NIM_FALLBACK_MODEL" not in os.environ:
        return NIM_FALLBACK_MODEL_DEFAULT
    return _env("NIM_FALLBACK_MODEL")


def nim_temperature(requested: Optional[float]) -> Optional[float]:
    """``NIM_TEMPERATURE`` wins when set. Otherwise the per-call temperature is kept."""
    raw = _env("NIM_TEMPERATURE")
    if raw:
        return _env_float(raw, 0.2 if requested is None else float(requested))
    if requested is None:
        return None
    return float(requested)


def nim_max_tokens(requested: int) -> int:
    raw = _env("NIM_MAX_TOKENS")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    if requested and int(requested) > 0:
        return int(requested)
    return NIM_MAX_TOKENS_DEFAULT


def nim_top_p() -> float:
    raw = _env("NIM_TOP_P")
    if raw:
        return _env_float(raw, NIM_TOP_P_DEFAULT)
    return NIM_TOP_P_DEFAULT


def nim_reasoning() -> str:
    return _env("NIM_REASONING") or NIM_REASONING_DEFAULT


def nim_extra_body() -> dict[str, Any]:
    """JSON object from ``NIM_EXTRA_BODY``. ``guided_json`` and ``nvext`` are never kept here."""
    raw = _env("NIM_EXTRA_BODY")
    if not raw:
        data: Any = dict(NIM_EXTRA_BODY_DEFAULT)
    else:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("NIM_EXTRA_BODY is not JSON; ignored")
            data = dict(NIM_EXTRA_BODY_DEFAULT)
    if not isinstance(data, dict):
        log.warning("NIM_EXTRA_BODY is not a JSON object; ignored")
        data = dict(NIM_EXTRA_BODY_DEFAULT)
    return {key: value for key, value in data.items() if key not in {"guided_json", "nvext"}}


def provider_timeout_seconds(provider: str = "") -> float:
    """Per-hop timeout. Super is 20 s and Lightning is 10 s unless that hop's env is set."""
    specific = _env(_TIMEOUT_ENV.get(provider, "")) if provider else ""
    if specific:
        value = _env_float(specific, DEFAULT_PROVIDER_TIMEOUT_S)
        return value if value > 0 else DEFAULT_PROVIDER_TIMEOUT_S
    if provider == "nim":
        return NIM_TIMEOUT_S
    if provider == "nim_fallback":
        return NIM_FALLBACK_TIMEOUT_S
    raw = _env("ESCALES_LLM_TIMEOUT_S")
    if not raw:
        return DEFAULT_PROVIDER_TIMEOUT_S
    value = _env_float(raw, DEFAULT_PROVIDER_TIMEOUT_S)
    if value <= 0:
        return DEFAULT_PROVIDER_TIMEOUT_S
    return value


def provider_timeout(provider: str = "") -> httpx.Timeout:
    seconds = provider_timeout_seconds(provider)
    return httpx.Timeout(seconds, connect=min(8.0, seconds))


def _temperature(requested: Optional[float], default: float) -> float:
    if requested is None:
        return default
    return float(requested)


def tokenfactory_url() -> str:
    base = (_env("NAVIGUIDE_TF_BASE") or TOKENFACTORY_DEFAULT_BASE).rstrip("/")
    return f"{base}/chat/completions"


def active_providers(order: Optional[tuple[str, ...]] = None) -> list[str]:
    """Configured HTTP hops, in cascade order. Nebius only when its flag is on."""
    ready = {
        "nim": bool(nvidia_key()),
        "nim_fallback": bool(nvidia_key()) and bool(nim_fallback_model()),
        "openrouter": bool(openrouter_key()),
        "anthropic": bool(anthropic_key()),
        "tokenfactory": nebius_enabled() and bool(nebius_key()),
    }
    names = order or HTTP_CASCADE
    return [name for name in names if ready.get(name)]


def has_llm() -> bool:
    """True when the master flag is on and at least one provider can run."""
    return llm_enabled() and bool(active_providers())


LLM_DAILY_CAP_DEFAULT = 100
_llm_day = ""
_llm_count = 0


class LlmBudgetExhausted(RuntimeError):
    """The production daily cap is full. Callers fall back to the rules."""


def _budget_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _limits_enabled() -> bool:
    from app.escales.config import limits_enabled

    return limits_enabled()


def _positive_env(name: str) -> Optional[int]:
    raw = _env(name)
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def llm_daily_cap() -> int:
    from app.escales.rate_limit import judging_window_active

    if judging_window_active():
        judging = _positive_env("ESCALES_LLM_DAILY_CAP_JUDGING")
        if judging is not None:
            return judging
    base = _positive_env("ESCALES_LLM_DAILY_CAP")
    if base is not None:
        return base
    return LLM_DAILY_CAP_DEFAULT


def reset_llm_budget() -> None:
    global _llm_day, _llm_count
    _llm_day = ""
    _llm_count = 0


def llm_calls_today() -> int:
    return _llm_count


def consume_llm_call(now: Optional[dt.datetime] = None) -> bool:
    """Reserve one LLM call. Always allowed, and not counted, outside production."""
    global _llm_day, _llm_count
    if not _limits_enabled():
        return True
    moment = now or _budget_now()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    day = moment.astimezone(dt.timezone.utc).date().isoformat()
    if day != _llm_day:
        _llm_day = day
        _llm_count = 0
    if _llm_count >= llm_daily_cap():
        return False
    _llm_count += 1
    return True


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=provider_timeout())


def _clean_text(txt: str | None) -> str:
    """Drop reasoning traces and a wrapping code fence. Keep the visitor sentence."""
    text = _THINK_BLOCK_RE.sub("", txt or "")
    text = _THINK_OPEN_RE.sub("", text).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    return text.strip()


def _json_object_slice(cleaned: str) -> str:
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("LLM JSON parse failed")
    return cleaned[start : end + 1]


class ProviderHTTPError(RuntimeError):
    """HTTP failure. The message is the status only. The body is never kept."""

    def __init__(self, provider: str, status: int, retry_after: Optional[float] = None) -> None:
        super().__init__(f"{provider} HTTP {status}")
        self.provider = provider
        self.status = int(status)
        self.retry_after = retry_after


def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
    raw = (response.headers.get("retry-after") or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        moment = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return max(0.0, (moment - dt.datetime.now(dt.timezone.utc)).total_seconds())


def _http_error(provider: str, response: httpx.Response) -> ProviderHTTPError:
    return ProviderHTTPError(provider, response.status_code, _retry_after_seconds(response))


# One pause inside this band, then the same NIM model is tried again.
NIM_RETRY_PAUSE_S = 0.75
# 429 still arrives at one call per second, so successive NIM calls sit further apart.
NIM_CALL_GAP_S = 1.25
_last_nim_at = 0.0


def nim_rate_limit_pause() -> float:
    """Seconds to wait after NIM HTTP 429 before the same model is retried."""
    return NIM_RETRY_PAUSE_S


def nim_retry_wait(retry_after: Optional[float]) -> float:
    """Honour Retry-After, capped at 3 s, and never wait less than the NIM gap."""
    floor = nim_call_gap()
    if retry_after is None:
        return max(floor, NIM_RETRY_PAUSE_S)
    capped = min(max(0.0, float(retry_after)), RETRY_AFTER_CAP_S)
    return max(capped, floor)


_hop_blocked_until: dict[str, float] = {}
_hop_block_reason: dict[str, str] = {}


def reset_hop_blocks() -> None:
    _hop_blocked_until.clear()
    _hop_block_reason.clear()


def hop_blocked(name: str) -> bool:
    return time.monotonic() < _hop_blocked_until.get(name, 0.0)


def hop_block_remaining(name: str) -> float:
    return max(0.0, _hop_blocked_until.get(name, 0.0) - time.monotonic())


def block_hop(name: str, reason: str, seconds: float = HOP_BLOCK_S) -> None:
    """Skip this hop. The log names the hop, never the key or the response body."""
    _hop_blocked_until[name] = time.monotonic() + seconds
    _hop_block_reason[name] = reason
    log.warning("model unavailable for this key; skipping %s", name)


def nim_call_gap() -> float:
    """Minimum seconds between NIM requests. Above one second: 429 still happens at 1/s."""
    raw = _env("ESCALES_NIM_GAP_S")
    if not raw:
        return NIM_CALL_GAP_S
    try:
        value = float(raw)
    except ValueError:
        return NIM_CALL_GAP_S
    return value if value >= 0 else NIM_CALL_GAP_S


def reset_nim_pace() -> None:
    global _last_nim_at
    _last_nim_at = 0.0


async def _pace_nim() -> None:
    """Wait until the previous NIM call is far enough behind."""
    global _last_nim_at
    gap = nim_call_gap()
    if _last_nim_at and gap > 0:
        wait = gap - (time.monotonic() - _last_nim_at)
        if wait > 0:
            await asyncio.sleep(wait)
    _last_nim_at = time.monotonic()


def _is_rate_limit(exc: BaseException) -> bool:
    return bool(re.search(r"\bHTTP\s+429\b", str(exc)))


def _failure_kind(exc: BaseException) -> str:
    """A short cause for logs and model_source.reason. No exception text, so no secret."""
    if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError, TimeoutError)):
        return "timeout"
    match = re.search(r"\bHTTP\s+(\d+)\b", str(exc))
    if match:
        return f"http_{match.group(1)}"
    return type(exc).__name__


def _public_failure(exc: BaseException) -> str:
    """Status or exception class for fallback_reason. No body and no key."""
    if isinstance(exc, ProviderHTTPError):
        return f"HTTP {exc.status}"
    match = re.search(r"\bHTTP\s+(\d+)\b", str(exc))
    if match:
        return f"HTTP {match.group(1)}"
    return type(exc).__name__


def _openai_text(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice, dict) else {}
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return _clean_text(content)
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and str(block.get("type") or "text") not in {"reasoning", "thinking"}:
                piece = block.get("text")
                if piece is None:
                    piece = block.get("content")
                if isinstance(piece, str):
                    parts.append(piece)
        return _clean_text("".join(parts))
    return ""


def _claude_text(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for block in data.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
        elif isinstance(block, str):
            parts.append(block)
    return _clean_text("\n".join(parts))


def _reported_model(data: dict[str, Any], requested: str) -> str:
    reported = str(data.get("model") or "").strip()
    return reported or requested


async def _post_json(
    client: httpx.AsyncClient,
    provider: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    response = await client.post(
        url, headers=headers, json=payload, timeout=provider_timeout(provider),
    )
    if response.status_code >= 400:
        raise _http_error(provider, response)
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"{provider} invalid JSON") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{provider} invalid JSON")
    return data


# Advisory schema for ask_json only. Never merged into NIM_EXTRA_BODY.
# nvext.guided_json returns 400, so the schema sits at the request root.
ADVISORY_PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "proposal": {
            "type": "string",
            "enum": ["capture", "void", "wait", "reauthorize"],
        },
        "reason": {"type": "string"},
    },
    "required": ["proposal", "reason"],
}


async def _call_nim(
    system: str,
    user: str,
    client: httpx.AsyncClient,
    max_tokens: int,
    temperature: Optional[float] = None,
    *,
    hop: str = "nim",
    model: Optional[str] = None,
    guided_json: Optional[dict[str, Any]] = None,
) -> LlmResult:
    key = nvidia_key()
    if not key:
        raise RuntimeError("NVIDIA_API_KEY missing")
    chosen = (model or "").strip() or (nim_fallback_model() if hop == "nim_fallback" else nim_model())
    if not chosen:
        raise RuntimeError("NIM model missing")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    payload: dict[str, Any] = {
        "model": chosen,
        "messages": messages,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    extra = nim_extra_body()
    if extra:
        payload.update(extra)
    payload["messages"] = messages
    payload["model"] = chosen
    payload["max_tokens"] = nim_max_tokens(max_tokens)
    payload.pop("reasoning_effort", None)
    chosen_temperature = nim_temperature(temperature)
    if chosen_temperature is None:
        payload.pop("temperature", None)
        payload.pop("top_p", None)
    elif chosen_temperature > 0:
        payload["temperature"] = chosen_temperature
        payload["top_p"] = nim_top_p()
    else:
        payload["temperature"] = chosen_temperature
        payload.pop("top_p", None)
    payload.pop("nvext", None)
    payload.pop("guided_json", None)
    payload.pop("reasoning_effort", None)
    if guided_json is not None:
        payload["guided_json"] = guided_json
    data = await _post_json(
        client,
        hop,
        NVIDIA_URL,
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        payload,
    )
    text = _openai_text(data)
    if not text:
        raise RuntimeError(f"{hop} empty")
    provider = "nim_fallback" if hop == "nim_fallback" else "nim"
    return LlmResult(text, provider, _reported_model(data, chosen))


def _json_schema_format(schema: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not schema:
        return None
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "advisory_proposal",
            "strict": True,
            "schema": schema,
        },
    }


async def _call_openrouter(
    system: str,
    user: str,
    client: httpx.AsyncClient,
    max_tokens: int,
    temperature: Optional[float] = None,
    response_schema: Optional[dict[str, Any]] = None,
) -> LlmResult:
    key = openrouter_key()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY missing")
    model = openrouter_model()
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": _temperature(temperature, 0.4),
    }
    formatted = _json_schema_format(response_schema)
    if formatted is not None:
        payload["response_format"] = formatted
    data = await _post_json(
        client,
        "openrouter",
        OPENROUTER_URL,
        {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": _env("OPENROUTER_HTTP_REFERER") or OPENROUTER_REFERER,
            "X-Title": _env("OPENROUTER_APP_TITLE") or OPENROUTER_TITLE,
        },
        payload,
    )
    text = _openai_text(data)
    if not text:
        raise RuntimeError("openrouter empty")
    return LlmResult(text, "openrouter", _reported_model(data, model))


async def _call_anthropic(
    system: str,
    user: str,
    client: httpx.AsyncClient,
    max_tokens: int,
    temperature: Optional[float] = None,
) -> LlmResult:
    key = anthropic_key()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY missing")
    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "temperature": _temperature(temperature, 0),
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    data = await _post_json(
        client,
        "anthropic",
        ANTHROPIC_URL,
        {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        payload,
    )
    text = _claude_text(data)
    if not text:
        raise RuntimeError("anthropic empty")
    return LlmResult(text, "anthropic", _reported_model(data, ANTHROPIC_MODEL))


async def _call_tokenfactory(
    system: str,
    user: str,
    client: httpx.AsyncClient,
    max_tokens: int,
    temperature: Optional[float] = None,
) -> LlmResult:
    key = nebius_key()
    if not key:
        raise RuntimeError("NEBIUS_API_KEY missing")
    if not nebius_enabled():
        raise RuntimeError("ESCALES_LLM_NEBIUS_ENABLED is off")
    payload = {
        "model": TOKENFACTORY_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": _temperature(temperature, 0.4),
        "stream": False,
        "reasoning_effort": "none",
        "chat_template_kwargs": {"enable_thinking": False},
    }
    data = await _post_json(
        client,
        "tokenfactory",
        tokenfactory_url(),
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        payload,
    )
    text = _openai_text(data)
    if not text:
        raise RuntimeError("tokenfactory empty")
    return LlmResult(text, "tokenfactory", _reported_model(data, TOKENFACTORY_MODEL))


_CALLS: dict[str, _Caller] = {
    "nim": _call_nim,
    "openrouter": _call_openrouter,
    "anthropic": _call_anthropic,
    "tokenfactory": _call_tokenfactory,
}


def log_effective_nim_models() -> None:
    """Startup line. Model ids only, never a key."""
    fallback = nim_fallback_model() or "-"
    log.info("effective NIM model ids primary=%s fallback=%s", nim_model(), fallback)


def _status_of(exc: BaseException) -> Optional[int]:
    if isinstance(exc, ProviderHTTPError):
        return exc.status
    match = re.search(r"\bHTTP\s+(\d+)\b", str(exc))
    if not match:
        return None
    return int(match.group(1))


def _hop_model_for_log(name: str) -> str:
    if name == "nim":
        return nim_model()
    if name == "nim_fallback":
        return nim_fallback_model()
    if name == "openrouter":
        return openrouter_model()
    return name


def _annotate_hop(result: Any) -> None:
    """Name the LangSmith run after the hop that answered. No-op when tracing is off."""
    provider = str(getattr(result, "provider", "") or "")
    model = str(getattr(result, "model", "") or "")
    annotate_run(
        name=f"{provider}/{model}" if model else provider or None,
        metadata={
            "ls_provider": provider,
            "ls_model_name": model,
            "fallback_reason": dict(getattr(result, "fallback_reason", None) or {}),
        },
    )


@traced("llm.ask_text", "llm")
async def ask_text(
    prompt: str,
    system: Optional[str] = None,
    max_tokens: int = 500,
    client: Optional[httpx.AsyncClient] = None,
    temperature: Optional[float] = None,
    guided_json: Optional[dict[str, Any]] = None,
    order: Optional[tuple[str, ...]] = None,
    lang: Optional[str] = None,
) -> LlmResult:
    """Run the cascade. Raises when no provider answers so the captain uses its rules.

    ``client`` is for tests. Production opens a short-lived client and closes it.
    ``temperature`` is the caller's preference. NIM uses it unless ``NIM_TEMPERATURE`` is set.
    ``guided_json`` is attached only to the NIM hops, at the request root.
    OpenRouter receives the same schema as ``response_format``.
    ``fallback_reason`` names each earlier hop by status or exception class.
    """
    if not has_llm():
        raise RuntimeError("No LLM configured")
    if not consume_llm_call():
        raise LlmBudgetExhausted("ESCALES_LLM_DAILY_CAP reached")
    system_text = (system or "").strip() or default_system(lang)
    user = prompt or ""
    budget = max(1, int(max_tokens))
    own = client is None
    http = client or _client()
    try:
        last = "no_llm_backend"
        primary_failure = ""
        failures: dict[str, str] = {}
        for name in active_providers(order):
            if hop_blocked(name):
                failures[name] = _hop_block_reason.get(name) or "HTTP 404"
                log.info("cascade %s skipped (unavailable for this key)", name)
                continue
            nim_hop = name in {"nim", "nim_fallback"}
            for attempt in range(2 if nim_hop else 1):
                try:
                    if nim_hop:
                        await _pace_nim()
                        sent = nim_fallback_model() if name == "nim_fallback" else nim_model()
                        if name == "nim" and nim_model_reason():
                            log.warning("NIM primary hop: %s", nim_model_reason())
                        log.info("NIM hop %s sending model %s", name, sent)
                        result = await _call_nim(
                            system_text,
                            user,
                            http,
                            budget,
                            temperature,
                            hop=name,
                            model=sent,
                            guided_json=guided_json,
                        )
                    elif name == "openrouter":
                        log.info("openrouter hop sending model %s", openrouter_model())
                        result = await _call_openrouter(
                            system_text,
                            user,
                            http,
                            budget,
                            temperature,
                            response_schema=guided_json,
                        )
                    else:
                        log.info("cascade hop %s sending model %s", name, _hop_model_for_log(name))
                        result = await _CALLS[name](system_text, user, http, budget, temperature)
                except Exception as exc:
                    detail = safe_error_message(exc)
                    kind = _failure_kind(exc)
                    public = _public_failure(exc)
                    malformed = nim_model_fallback_reason() if name == "nim" else {}
                    failures[name] = malformed.get("nim") or public
                    last = f"{name} {kind}"
                    log.warning(
                        "cascade %s failed (%s) model=%s: %s",
                        name,
                        kind,
                        _hop_model_for_log(name),
                        detail,
                    )
                    status = _status_of(exc)
                    if status in {403, 404}:
                        block_hop(name, public)
                        if name == "nim" and status == 404:
                            global _nim_404_fallbacks
                            _nim_404_fallbacks += 1
                            log.warning(
                                "NIM model %s returned 404; falling back (count=%s)",
                                nim_model(),
                                _nim_404_fallbacks,
                            )
                    if name == "nim":
                        primary_failure = kind
                    if attempt == 0 and nim_hop and _is_rate_limit(exc):
                        retry_after = exc.retry_after if isinstance(exc, ProviderHTTPError) else None
                        pause = nim_retry_wait(retry_after)
                        log.warning("cascade %s HTTP 429, retrying once in %.2fs", name, pause)
                        await asyncio.sleep(pause)
                        continue
                    if name == "openrouter" and status == 429:
                        retry_after = exc.retry_after if isinstance(exc, ProviderHTTPError) else None
                        pause = min(max(0.0, retry_after or 0.0), RETRY_AFTER_CAP_S)
                        if pause:
                            log.warning("cascade openrouter HTTP 429, waiting %.2fs then skipping", pause)
                            await asyncio.sleep(pause)
                    if status == 402:
                        log.warning("cascade %s HTTP 402, skipping provider", name)
                    break
                if result.text.strip():
                    failures.pop(name, None)
                    result.fallback_reason = dict(failures)
                    malformed = nim_model_fallback_reason() if name == "nim" else {}
                    if malformed:
                        result.fallback_reason = {**malformed, **result.fallback_reason}
                    if name == "nim" and nim_model_reason():
                        result.reason = nim_model_reason()
                    elif name == "nim_fallback" and (order or HTTP_CASCADE)[0] == "nim":
                        result.reason = (
                            f"primary hop sent {nim_model()} and failed ({primary_failure or 'error'}); "
                            f"nim_fallback sent {result.model}"
                        )
                        log.warning("%s", result.reason)
                    elif failures and not result.reason:
                        result.reason = "; ".join(f"{hop} {cause}" for hop, cause in failures.items())
                    _annotate_hop(result)
                    return result
                last = f"{name} empty"
                failures[name] = "empty"
                if name == "nim":
                    primary_failure = "empty"
                break
        raise RuntimeError(f"LLM cascade exhausted ({last})")
    finally:
        if own:
            await http.aclose()


class LlmJson:
    """Parsed JSON object plus the provider and model that wrote it."""

    def __init__(self, data: dict[str, Any], provider: str, model: str, text: str) -> None:
        self.data = data
        self.provider = provider
        self.model = model
        self.text = text

    def __bool__(self) -> bool:
        return bool(self.data)


_JSON_SYSTEM = "Reply with one JSON object only. No markdown fence and no commentary."


def advisory_matches_schema(data: Any) -> bool:
    """Hand check of ADVISORY_PROPOSAL_SCHEMA. No extra library."""
    if not isinstance(data, dict):
        return False
    allowed = ADVISORY_PROPOSAL_SCHEMA["properties"]["proposal"]["enum"]
    proposal = data.get("proposal")
    reason = data.get("reason")
    if proposal not in allowed:
        return False
    return isinstance(reason, str) and bool(reason.strip())


def parse_json_object(text: str) -> dict[str, Any]:
    """Accept a raw object or one JSON object wrapped in prose, fences, or reasoning."""
    cleaned = _clean_text(text)
    snippet = _json_object_slice(cleaned)
    try:
        data = json.loads(snippet)
    except json.JSONDecodeError as exc:
        raise RuntimeError("LLM JSON parse failed") from exc
    if not isinstance(data, dict):
        raise RuntimeError("LLM JSON was not an object")
    return data


async def complete(
    prompt: str,
    *,
    lang: str,
    system: Optional[str] = None,
    max_tokens: int = 500,
    client: Optional[httpx.AsyncClient] = None,
    temperature: Optional[float] = None,
    guided_json: Optional[dict[str, Any]] = None,
    order: Optional[tuple[str, ...]] = None,
) -> LlmResult:
    return await ask_text(
        prompt,
        system=system,
        max_tokens=max_tokens,
        client=client,
        temperature=temperature,
        guided_json=guided_json,
        order=order,
        lang=lang,
    )


@traced("llm.ask_json", "llm")
async def ask_json(
    prompt: str,
    system: Optional[str] = None,
    max_tokens: int = 500,
    client: Optional[httpx.AsyncClient] = None,
    temperature: Optional[float] = 0,
    schema: Optional[dict[str, Any]] = None,
    lang: Optional[str] = None,
) -> LlmJson:
    """Ask for one JSON object. The schema is advisory and does not choose the payment."""
    system_text = (system or "").strip() or default_json_system(lang)
    use_schema = schema or ADVISORY_PROPOSAL_SCHEMA
    result = await ask_text(
        prompt,
        system=system_text,
        max_tokens=max_tokens,
        client=client,
        temperature=0 if temperature is None else temperature,
        guided_json=use_schema,
        order=JSON_HTTP_CASCADE,
        lang=lang,
    )
    data = parse_json_object(result.text)
    if not advisory_matches_schema(data):
        raise RuntimeError("advisory schema mismatch: need proposal (capture|void|wait|reauthorize) and reason")
    parsed = LlmJson(data, result.provider, result.model, result.text)
    parsed.fallback_reason = result.fallback_reason
    _annotate_hop(parsed)
    return parsed


async def complete_json(
    prompt: str,
    *,
    lang: str,
    system: Optional[str] = None,
    max_tokens: int = 500,
    client: Optional[httpx.AsyncClient] = None,
    temperature: Optional[float] = 0,
    schema: Optional[dict[str, Any]] = None,
) -> LlmJson:
    return await ask_json(
        prompt,
        system=system,
        max_tokens=max_tokens,
        client=client,
        temperature=temperature,
        schema=schema,
        lang=lang,
    )


def llm_result_metadata(result: LlmResult) -> dict[str, Any]:
    """Provider and model only. No prompt text and no keys."""
    payload: dict[str, Any] = {
        "provider": result.provider,
        "model": result.model,
    }
    if result.fallback_reason:
        payload["fallback_reason"] = dict(result.fallback_reason)
    if result.reason:
        payload["reason"] = result.reason
    return payload


def _probe_error_metadata(exc: BaseException) -> dict[str, Any]:
    """Error type plus the redacted message (schema mismatch, parse failure, all hops failed)."""
    return {
        "provider": "none",
        "model": "",
        "error": type(exc).__name__,
        "message": safe_error_message(exc),
    }


# A valid advisory the probe asks for. Reasoning models need room to think first.
PROBE_ADVISORY_PROMPT = (
    'Return one JSON object with exactly two keys: "proposal", one of '
    '"capture", "void", "wait" or "reauthorize"; and "reason", one short sentence. '
    'Context: a stop has no arrival evidence yet. Answer with proposal "wait".'
)
PROBE_ADVISORY_MAX_TOKENS = 1200


async def probe_cascade(client: Optional[httpx.AsyncClient] = None) -> dict[str, Any]:
    """One hop through each call shape (chat, report, ask_json). Metadata only."""
    if not has_llm():
        empty = {"provider": "rules", "model": ""}
        return {"chat": empty, "report": empty, "ask_json": empty}

    chat_system = "Reply with the single word ok."
    report_system = "Reply with the single word ok."

    try:
        chat_result = await ask_text(
            "cascade probe chat",
            system=chat_system,
            max_tokens=8,
            client=client,
            temperature=0.3,
            order=HTTP_CASCADE,
            lang="en",
        )
        chat_meta = llm_result_metadata(chat_result)
    except Exception as exc:
        chat_meta = _probe_error_metadata(exc)

    try:
        report_result = await ask_text(
            "cascade probe report",
            system=report_system,
            max_tokens=8,
            client=client,
            temperature=0.2,
            order=HTTP_CASCADE,
            lang="en",
        )
        report_meta = llm_result_metadata(report_result)
    except Exception as exc:
        report_meta = _probe_error_metadata(exc)

    try:
        advisory = await ask_json(
            PROBE_ADVISORY_PROMPT,
            system=default_json_system("en"),
            max_tokens=PROBE_ADVISORY_MAX_TOKENS,
            client=client,
            temperature=0,
            lang="en",
        )
        ask_meta = {
            "provider": advisory.provider,
            "model": advisory.model,
        }
        fallback = getattr(advisory, "fallback_reason", None)
        if fallback:
            ask_meta["fallback_reason"] = dict(fallback)
    except Exception as exc:
        ask_meta = _probe_error_metadata(exc)

    return {"chat": chat_meta, "report": report_meta, "ask_json": ask_meta}
