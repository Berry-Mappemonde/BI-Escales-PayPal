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
NIM_FALLBACK_TIMEOUT_S = 8.0
# Attribute kept so a script can still assign llm.NIM_MODEL. Env wins.
NIM_MODEL = NIM_MODEL_DEFAULT

OPENROUTER_DEFAULT_MODEL = "openai/gpt-4o-mini"
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
_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.IGNORECASE | re.DOTALL)
_THINK_OPEN_RE = re.compile(r"<think\b[^>]*>.*\Z", re.IGNORECASE | re.DOTALL)

_DEFAULT_SYSTEM = (
    "You are the Blue Intelligence Escales captain. "
    "You propose only. You never capture, void, or move money."
)

_Caller = Callable[..., Awaitable["LlmResult"]]


class LlmResult:
    """Model text plus the provider and model id that produced it.

    ``reason`` is a short cause when the hop is not the configured primary
    success. It names model ids and failure kinds only, never a secret.
    """

    def __init__(self, text: str, provider: str, model: str, reason: str = "") -> None:
        self.text = text
        self.provider = provider
        self.model = model
        self.reason = reason

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


def nim_model_reason() -> str:
    """Why the primary id is not the raw ``NIM_MODEL`` value. Empty when it is used as set."""
    return _nim_model_reason


def nim_model() -> str:
    """Primary NIM id. ``NIM_MODEL`` env, else the module attribute, else the benchmarked default.

    A known 404 id, or the lightning id placed in ``NIM_MODEL``, is not sent.
    The private Super id is sent instead, and ``nim_model_reason`` says so.
    """
    global _nim_model_reason
    configured = _env("NIM_MODEL")
    chosen = configured or (NIM_MODEL or "").strip() or NIM_MODEL_DEFAULT
    why = _NIM_REJECTED_IDS.get(chosen)
    if why:
        _nim_model_reason = (
            f"NIM_MODEL is {chosen}, which {why}. "
            f"The primary hop sends {NIM_MODEL_DEFAULT}. "
            "On Render, set NIM_MODEL to that id or unset it."
        )
        return NIM_MODEL_DEFAULT
    _nim_model_reason = ""
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
    """Per-provider timeout. The NIM fallback stays at 8 s unless its own env is set."""
    specific = _env(_TIMEOUT_ENV.get(provider, "")) if provider else ""
    if specific:
        value = _env_float(specific, DEFAULT_PROVIDER_TIMEOUT_S)
        return value if value > 0 else DEFAULT_PROVIDER_TIMEOUT_S
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


def active_providers() -> list[str]:
    """Configured HTTP hops, in cascade order. Nebius only when its flag is on."""
    ready = {
        "nim": bool(nvidia_key()),
        "nim_fallback": bool(nvidia_key()) and bool(nim_fallback_model()),
        "openrouter": bool(openrouter_key()),
        "anthropic": bool(anthropic_key()),
        "tokenfactory": nebius_enabled() and bool(nebius_key()),
    }
    return [name for name in HTTP_CASCADE if ready[name]]


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


def llm_daily_cap() -> int:
    raw = _env("ESCALES_LLM_DAILY_CAP")
    if not raw:
        return LLM_DAILY_CAP_DEFAULT
    try:
        value = int(raw)
    except ValueError:
        return LLM_DAILY_CAP_DEFAULT
    return value if value > 0 else LLM_DAILY_CAP_DEFAULT


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
    """Drop thinking traces and a wrapping code fence. Keep the visitor sentence."""
    text = _THINK_BLOCK_RE.sub("", txt or "")
    text = _THINK_OPEN_RE.sub("", text).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text.strip()


def _http_error(provider: str, response: httpx.Response) -> RuntimeError:
    return RuntimeError(f"{provider} HTTP {response.status_code}")


# One pause inside this band, then the same NIM model is tried again.
NIM_RETRY_PAUSE_S = 0.75
# 429 still arrives at one call per second, so successive NIM calls sit further apart.
NIM_CALL_GAP_S = 1.25
_last_nim_at = 0.0


def nim_rate_limit_pause() -> float:
    """Seconds to wait after NIM HTTP 429 before the same model is retried."""
    return NIM_RETRY_PAUSE_S


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
    payload["top_p"] = nim_top_p()
    payload["reasoning_effort"] = nim_reasoning()
    chosen_temperature = nim_temperature(temperature)
    if chosen_temperature is None:
        payload.pop("temperature", None)
    else:
        payload["temperature"] = chosen_temperature
    payload.pop("nvext", None)
    payload.pop("guided_json", None)
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


async def _call_openrouter(
    system: str,
    user: str,
    client: httpx.AsyncClient,
    max_tokens: int,
    temperature: Optional[float] = None,
) -> LlmResult:
    key = openrouter_key()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY missing")
    model = openrouter_model()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": _temperature(temperature, 0.4),
    }
    data = await _post_json(
        client,
        "openrouter",
        OPENROUTER_URL,
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
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


async def ask_text(
    prompt: str,
    system: Optional[str] = None,
    max_tokens: int = 500,
    client: Optional[httpx.AsyncClient] = None,
    temperature: Optional[float] = None,
    guided_json: Optional[dict[str, Any]] = None,
) -> LlmResult:
    """Run the cascade. Raises when no provider answers so the captain uses its rules.

    ``client`` is for tests. Production opens a short-lived client and closes it.
    ``temperature`` is the caller's preference. NIM uses it unless ``NIM_TEMPERATURE`` is set.
    ``guided_json`` is attached only to the NIM hops, at the request root.
    """
    if not has_llm():
        raise RuntimeError("No LLM configured")
    if not consume_llm_call():
        raise LlmBudgetExhausted("ESCALES_LLM_DAILY_CAP reached")
    system_text = (system or "").strip() or _DEFAULT_SYSTEM
    user = prompt or ""
    budget = max(1, int(max_tokens))
    own = client is None
    http = client or _client()
    try:
        last = "no_llm_backend"
        primary_failure = ""
        for name in active_providers():
            nim_hop = name in {"nim", "nim_fallback"}
            for attempt in range(2 if nim_hop else 1):
                try:
                    if nim_hop:
                        await _pace_nim()
                        sent = nim_fallback_model() if name == "nim_fallback" else nim_model()
                        if name == "nim" and nim_model_reason():
                            log.warning("NIM primary hop: %s", nim_model_reason())
                        else:
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
                    else:
                        result = await _CALLS[name](system_text, user, http, budget, temperature)
                except Exception as exc:
                    detail = safe_error_message(exc)
                    kind = _failure_kind(exc)
                    last = f"{name} {kind}"
                    log.warning(
                        "cascade %s failed (%s) model=%s: %s",
                        name,
                        kind,
                        nim_model() if name == "nim" else (nim_fallback_model() if name == "nim_fallback" else name),
                        detail,
                    )
                    if name == "nim":
                        primary_failure = kind
                        if kind == "http_404":
                            global _nim_404_fallbacks
                            _nim_404_fallbacks += 1
                            log.warning(
                                "NIM model %s returned 404; falling back (count=%s)",
                                nim_model(),
                                _nim_404_fallbacks,
                            )
                    if attempt == 0 and nim_hop and _is_rate_limit(exc):
                        pause = nim_rate_limit_pause()
                        log.warning("cascade %s HTTP 429, retrying once in %.2fs", name, pause)
                        await asyncio.sleep(pause)
                        continue
                    break
                if result.text.strip():
                    if name == "nim" and nim_model_reason():
                        result.reason = nim_model_reason()
                    elif name == "nim_fallback":
                        result.reason = (
                            f"primary hop sent {nim_model()} and failed ({primary_failure or 'error'}); "
                            f"nim_fallback sent {result.model}"
                        )
                        log.warning("%s", result.reason)
                    return result
                last = f"{name} empty"
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


def parse_json_object(text: str) -> dict[str, Any]:
    """Accept a raw object or one JSON object wrapped in prose or a fence."""
    cleaned = _clean_text(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("LLM JSON parse failed")
        data = json.loads(cleaned[start:end + 1])
    if not isinstance(data, dict):
        raise RuntimeError("LLM JSON was not an object")
    return data


async def ask_json(
    prompt: str,
    system: Optional[str] = None,
    max_tokens: int = 500,
    client: Optional[httpx.AsyncClient] = None,
    temperature: Optional[float] = 0,
) -> LlmJson:
    """Ask for one JSON object. The schema is advisory and does not choose the payment."""
    system_text = (system or "").strip() or _JSON_SYSTEM
    result = await ask_text(
        prompt,
        system=system_text,
        max_tokens=max_tokens,
        client=client,
        temperature=0 if temperature is None else temperature,
        guided_json=ADVISORY_PROPOSAL_SCHEMA,
    )
    return LlmJson(parse_json_object(result.text), result.provider, result.model, result.text)
