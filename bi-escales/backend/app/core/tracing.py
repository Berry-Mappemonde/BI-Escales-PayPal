"""Optional LangSmith tracing for the captain and the LLM cascade.

Tracing is off unless ``LANGSMITH_TRACING`` is ``true`` and ``LANGSMITH_API_KEY``
is set. When it is off, ``langsmith`` is never imported and no network call is
made. The project and endpoint come from ``LANGSMITH_PROJECT`` and
``LANGSMITH_ENDPOINT``; nothing is hardcoded here.

Inputs and outputs pass through ``redact`` before they leave the process:
contributor names, emails, payer data, card-like numbers and the treasurer key
are removed. Pledge ids, amounts, stop ids, PayPal resource ids, model names,
latency and the verdict are kept.

A tracing failure never breaks a reply: the wrapped function still runs once
and its own result or error is what the caller sees.
"""
from __future__ import annotations

import contextvars
import functools
import json
import logging
import os
import re
import uuid
from typing import Any, Awaitable, Callable, Optional, TypeVar

log = logging.getLogger("escales.tracing")

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])

REDACTED = "[redacted]"
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_CARD_LIKE = re.compile(r"(?<![\w])(?:\d[ -]?){12,18}\d(?![\w])")
_BEARER = re.compile(r"(?i)\bbearer\s+\S+")

# Keys whose values are personal or secret. Compared after lowercasing and
# replacing ``-`` with ``_``.
_DROP_KEYS = frozenset({
    "name", "full_name", "given_name", "surname", "family_name", "display_name",
    "first_name", "last_name", "contributor", "contributor_name", "donor",
    "donor_name", "supporter", "supporter_name",
    "email", "email_address", "payer", "payer_id", "payer_email", "payer_name",
    "payer_info", "payment_source", "shipping", "address", "phone",
    "phone_number", "card", "card_number", "number", "cvv", "security_code",
    "x_admin_key", "admin_key", "treasurer_key", "escales_admin_key",
    "authorization", "api_key", "secret", "client_secret", "password", "token",
    "access_token",
})
# Arguments that are objects, not data (HTTP client, PayPal reader).
_DROP_ARGS = frozenset({"client", "reader"})


def tracing_enabled() -> bool:
    """True only with ``LANGSMITH_TRACING=true`` and a non-empty API key."""
    flag = (os.environ.get("LANGSMITH_TRACING") or "").strip().lower()
    key = (os.environ.get("LANGSMITH_API_KEY") or "").strip()
    return flag == "true" and bool(key)


def _secret_values() -> list[str]:
    values = []
    for name in ("ESCALES_ADMIN_KEY", "LANGSMITH_API_KEY"):
        value = (os.environ.get(name) or "").strip()
        if len(value) >= 4:
            values.append(value)
    return values


def redact_text(text: str) -> str:
    """Strip emails, card-like numbers, bearer tokens and the treasurer key."""
    out = str(text)
    for secret in _secret_values():
        out = out.replace(secret, REDACTED)
    out = _BEARER.sub("Bearer " + REDACTED, out)
    out = _EMAIL.sub("[email]", out)
    out = _CARD_LIKE.sub("[card]", out)
    return out


def _drop_key(key: Any) -> bool:
    return str(key).strip().lower().replace("-", "_") in _DROP_KEYS


def _redact_json_string(text: str) -> Optional[str]:
    """A prompt that is a JSON object is redacted field by field."""
    stripped = text.strip()
    if not stripped.startswith(("{", "[")):
        return None
    try:
        data = json.loads(stripped)
    except (ValueError, TypeError):
        return None
    return json.dumps(redact(data), ensure_ascii=False, default=str)


def redact(value: Any, _depth: int = 0) -> Any:
    """Copy of ``value`` safe to send to LangSmith."""
    if _depth > 12:
        return REDACTED
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        structured = _redact_json_string(value)
        return structured if structured is not None else redact_text(value)
    if isinstance(value, dict):
        return {
            str(key): (REDACTED if _drop_key(key) else redact(item, _depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact(item, _depth + 1) for item in value]
    # Result objects (LlmResult, LlmJson): their public attributes only.
    attrs = getattr(value, "__dict__", None)
    if isinstance(attrs, dict):
        public = {k: v for k, v in attrs.items() if not k.startswith("_")}
        return redact(public, _depth + 1)
    return redact_text(str(value))


def redact_inputs(inputs: dict) -> dict:
    try:
        kept = {k: v for k, v in (inputs or {}).items() if k not in _DROP_ARGS}
        return redact(kept)
    except Exception:  # pragma: no cover - defensive
        return {}


def redact_outputs(outputs: Any) -> dict:
    try:
        cleaned = redact(outputs)
    except Exception:  # pragma: no cover - defensive
        return {}
    return cleaned if isinstance(cleaned, dict) else {"output": cleaned}


def annotate_run(name: Optional[str] = None, metadata: Optional[dict] = None) -> None:
    """Rename the current run or add metadata. Silent when tracing is off."""
    if not tracing_enabled():
        return
    try:
        from langsmith.run_helpers import get_current_run_tree

        run = get_current_run_tree()
        if run is None:
            return
        if name:
            run.name = name
        if metadata:
            run.metadata.update(redact(metadata))
    except Exception as exc:
        log.debug("tracing annotate skipped: %s", type(exc).__name__)


# Per-call progress of the wrapped function, so a tracing failure can be told
# apart from the function's own error.
_STATE: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "escales_trace_state", default=None,
)


def traced(name: str, run_type: str, *, attach_trace_id: bool = False) -> Callable[[F], F]:
    """``langsmith.traceable`` behind the env gate, with redaction.

    With ``attach_trace_id`` a dict result gets ``trace_id``: the LangSmith run
    id, or ``None`` when tracing is off.
    """

    def decorator(fn: F) -> F:
        built: dict[str, Any] = {}

        @functools.wraps(fn)
        async def body(*args: Any, **kwargs: Any) -> Any:
            state = _STATE.get()
            if state is not None:
                state["started"] = True
            try:
                result = await fn(*args, **kwargs)
            except BaseException as exc:
                if state is not None:
                    state["error"] = exc
                raise
            if state is not None:
                state["done"] = True
                state["result"] = result
            return result

        def tracer() -> Optional[Callable[..., Awaitable[Any]]]:
            try:
                from langsmith import traceable
            except Exception as exc:
                if not built.get("warned"):
                    log.warning("LangSmith tracing unavailable: %s", type(exc).__name__)
                    built["warned"] = True
                return None
            if built.get("source") is not traceable:
                try:
                    built["fn"] = traceable(
                        name=name,
                        run_type=run_type,
                        process_inputs=redact_inputs,
                        process_outputs=redact_outputs,
                    )(body)
                    built["source"] = traceable
                except Exception as exc:
                    log.warning("LangSmith traceable failed for %s: %s", name, type(exc).__name__)
                    return None
            return built["fn"]

        def finish(result: Any, run_id: Optional[uuid.UUID]) -> Any:
            if attach_trace_id and isinstance(result, dict):
                result["trace_id"] = str(run_id) if run_id else None
            return result

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not tracing_enabled():
                return finish(await fn(*args, **kwargs), None)
            run = tracer()
            if run is None:
                return finish(await fn(*args, **kwargs), None)
            run_id = uuid.uuid4()
            state: dict[str, Any] = {}
            token = _STATE.set(state)
            try:
                result = await run(*args, langsmith_extra={"run_id": run_id}, **kwargs)
            except BaseException as exc:
                if state.get("error") is exc:
                    raise
                if state.get("done"):
                    log.warning("LangSmith tracing failed after %s: %s", name, type(exc).__name__)
                    return finish(state.get("result"), None)
                if not state.get("started"):
                    log.warning("LangSmith tracing failed before %s: %s", name, type(exc).__name__)
                    _STATE.reset(token)
                    token = None
                    return finish(await fn(*args, **kwargs), None)
                raise
            finally:
                if token is not None:
                    _STATE.reset(token)
            return finish(result, run_id)

        wrapper.__wrapped_untraced__ = fn  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator
