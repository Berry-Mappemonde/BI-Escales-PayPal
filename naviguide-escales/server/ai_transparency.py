"""Machine-readable flags on text produced by a language model."""
from __future__ import annotations

import functools
import re
from datetime import datetime, timezone
from typing import Any

_LLM_SOURCES = frozenset({
    "nemotron-nano",
    "nemotron-lightning",
    "nemotron-super",
    "nemotron-super-vl",
    "nemotron-ultra",
    "openrouter",
    "claude",
    "cache",
})

_NOT_AI = frozenset({"", "rules", "budget"})
_MODEL_RE = re.compile(r"gpt-oss|nvidia-gpt|\bnim\b", re.I)


def is_ai_generated_source(source: str | None) -> bool:
    s = str(source or "").strip().lower()
    if not s or s.endswith("+local") or s in _NOT_AI:
        return False
    if s in _LLM_SOURCES or "nemotron" in s:
        return True
    return bool(_MODEL_RE.search(s))


def _payload_text(payload: dict[str, Any]) -> str:
    if "text" in payload:
        raw = payload.get("text")
    else:
        raw = payload.get("answer")
    return raw.strip() if isinstance(raw, str) else ""


def _unwrap_engine(engine: str | None) -> str:
    eng = str(engine or "").strip()
    if eng.lower().startswith("cache:"):
        return eng.split(":", 1)[1].strip()
    return eng


def text_is_ai_generated(payload: dict[str, Any]) -> bool:
    if not _payload_text(payload):
        return False
    engine = str(payload.get("engine") or "")
    source = str(payload.get("source") or "")
    if engine.endswith("+local") or source.endswith("+local"):
        return False
    inner = _unwrap_engine(engine)
    if inner and inner != engine:
        return is_ai_generated_source(inner)
    return is_ai_generated_source(source or engine)


def _model_name(payload: dict[str, Any]) -> str:
    explicit = str(payload.get("model") or "").strip()
    source = str(payload.get("source") or "").strip()
    inner = _unwrap_engine(payload.get("engine"))
    if explicit and is_ai_generated_source(explicit):
        return explicit
    # OpenRouter's own id (gpt-4o-mini), the same way NIM keeps gpt-oss.
    if explicit and (
        source.lower() == "openrouter" or str(inner).lower() == "openrouter"
    ):
        return explicit
    if inner and is_ai_generated_source(inner):
        return inner
    if source:
        return source
    return inner or source


def _stamp(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = float(value)
        if n > 10_000_000_000:
            n = n / 1000.0
        try:
            return datetime.fromtimestamp(n, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    return text or None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def transparency_fields(source: str | None, engine: str | None = None) -> dict[str, Any]:
    payload = {"source": source, "engine": engine, "text": "x"}
    if text_is_ai_generated(payload):
        model = _model_name(payload)
        return {"ai_generated": True, "ai_model": model, "model": model}
    return {"ai_generated": False}


def enrich_llm_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return payload or {}
    out = dict(payload)
    ai = text_is_ai_generated(out)
    out["ai_generated"] = ai
    if not ai:
        out.pop("ai_model", None)
        return out
    model = _model_name(out)
    out["ai_model"] = model
    if not str(out.get("model") or "").strip():
        out["model"] = model
    if not str(out.get("generated_at") or "").strip():
        out["generated_at"] = _stamp(out.get("t")) or _stamp(out.get("cachedAt")) or _utc_now()
    return out


def with_ai_transparency(fn):
    """Add the flags to a dict returned by an async writer."""

    @functools.wraps(fn)
    async def wrapped(*args, **kwargs):
        out = await fn(*args, **kwargs)
        if not isinstance(out, dict):
            return out
        return enrich_llm_payload(out)

    return wrapped
