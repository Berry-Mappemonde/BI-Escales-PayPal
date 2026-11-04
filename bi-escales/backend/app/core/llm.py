"""LLM cascade for the Escales captain.

Order, to spare Nebius credits: NVIDIA NIM, OpenRouter, Anthropic, then
Nebius Token Factory, then the deterministic rules in the captain.

Each provider runs only when its API key is set. The master flag
``ESCALES_LLM_ENABLED`` is off by default: ``has_llm()`` is false and no
HTTP call is made. Nebius stays implemented but stays off unless
``ESCALES_LLM_NEBIUS_ENABLED`` is truthy, and even then it is the last
resort before the rules.

The captain proposes. This module never captures, voids, or moves money.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Awaitable, Callable, Optional

import httpx

log = logging.getLogger("escales.llm")

# HTTP hops, then the local rules applied by the captain when nothing answered.
CASCADE = ("nim", "openrouter", "anthropic", "tokenfactory", "rules")
HTTP_CASCADE = ("nim", "openrouter", "anthropic", "tokenfactory")

NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
TOKENFACTORY_DEFAULT_BASE = "https://api.tokenfactory.nebius.com/v1"

NIM_MODEL = "openai/gpt-oss-20b"
OPENROUTER_DEFAULT_MODEL = "openai/gpt-4o-mini"
ANTHROPIC_MODEL = "claude-haiku-4-5"
TOKENFACTORY_MODEL = "nvidia/Nemotron-3.5-Super-VL"

TIMEOUT = httpx.Timeout(25.0, connect=8.0)
_TRUTHY = {"1", "true", "yes", "on"}
_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.IGNORECASE | re.DOTALL)
_THINK_OPEN_RE = re.compile(r"<think\b[^>]*>.*\Z", re.IGNORECASE | re.DOTALL)

_DEFAULT_SYSTEM = (
    "You are the Blue Intelligence Escales captain. "
    "You propose only. You never capture, void, or move money."
)

_Caller = Callable[[str, str, httpx.AsyncClient, int], Awaitable["LlmResult"]]


class LlmResult:
    """Model text plus the provider and model id that produced it."""

    def __init__(self, text: str, provider: str, model: str) -> None:
        self.text = text
        self.provider = provider
        self.model = model

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


def tokenfactory_url() -> str:
    base = (_env("NAVIGUIDE_TF_BASE") or TOKENFACTORY_DEFAULT_BASE).rstrip("/")
    return f"{base}/chat/completions"


def active_providers() -> list[str]:
    """Configured HTTP hops, in cascade order. Nebius only when its flag is on."""
    ready = {
        "nim": bool(nvidia_key()),
        "openrouter": bool(openrouter_key()),
        "anthropic": bool(anthropic_key()),
        "tokenfactory": nebius_enabled() and bool(nebius_key()),
    }
    return [name for name in HTTP_CASCADE if ready[name]]


def has_llm() -> bool:
    """True when the master flag is on and at least one provider can run."""
    return llm_enabled() and bool(active_providers())


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT)


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
    response = await client.post(url, headers=headers, json=payload)
    if response.status_code >= 400:
        raise _http_error(provider, response)
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"{provider} invalid JSON") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{provider} invalid JSON")
    return data


async def _call_nim(
    system: str, user: str, client: httpx.AsyncClient, max_tokens: int,
) -> LlmResult:
    key = nvidia_key()
    if not key:
        raise RuntimeError("NVIDIA_API_KEY missing")
    payload = {
        "model": NIM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "stream": False,
        "temperature": 0.6,
        "top_p": 0.7,
        "reasoning_effort": "low",
        "chat_template_kwargs": {"thinking": False},
    }
    data = await _post_json(
        client,
        "nim",
        NVIDIA_URL,
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        payload,
    )
    text = _openai_text(data)
    if not text:
        raise RuntimeError("nim empty")
    return LlmResult(text, "nim", _reported_model(data, NIM_MODEL))


async def _call_openrouter(
    system: str, user: str, client: httpx.AsyncClient, max_tokens: int,
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
        "temperature": 0.4,
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
    system: str, user: str, client: httpx.AsyncClient, max_tokens: int,
) -> LlmResult:
    key = anthropic_key()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY missing")
    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "temperature": 0,
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
    system: str, user: str, client: httpx.AsyncClient, max_tokens: int,
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
        "temperature": 0.4,
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
) -> LlmResult:
    """Run the cascade. Raises when no provider answers so the captain uses its rules.

    ``client`` is for tests. Production opens a short-lived client and closes it.
    """
    if not has_llm():
        raise RuntimeError("No LLM configured")
    system_text = (system or "").strip() or _DEFAULT_SYSTEM
    user = prompt or ""
    budget = max(1, int(max_tokens))
    own = client is None
    http = client or _client()
    try:
        last = "no_llm_backend"
        for name in active_providers():
            try:
                result = await _CALLS[name](system_text, user, http, budget)
            except Exception as exc:
                last = f"{name} {type(exc).__name__}"
                log.warning("cascade %s failed (%s)", name, type(exc).__name__)
                continue
            if result.text.strip():
                return result
            last = f"{name} empty"
        raise RuntimeError(f"LLM cascade exhausted ({last})")
    finally:
        if own:
            await http.aclose()
