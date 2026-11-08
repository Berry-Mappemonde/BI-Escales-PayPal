"""LangSmith tracing: off by default, redacted, never breaks a reply."""
import asyncio
import os
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.core import llm, tracing
from app.escales import ledger
from app.escales.captain import chat, review
from app.escales.toolkit_tools import ReadOnlyTools

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def no_llm(monkeypatch):
    monkeypatch.setenv("ESCALES_TOOLKIT_ENABLED", "0")
    monkeypatch.setattr(ledger, "_ledger", ledger.MemoryLedger())
    monkeypatch.setattr(llm, "has_llm", lambda *a, **kw: False)


@pytest.fixture
def tracing_off(monkeypatch):
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)


class FakeLangsmith:
    """Stand-in for ``langsmith.traceable``. Records what would be sent."""

    def __init__(self, fail: str = ""):
        self.fail = fail
        self.sent: list[dict] = []
        self.calls = 0

    def module(self) -> types.ModuleType:
        mod = types.ModuleType("langsmith")
        mod.traceable = self.traceable
        return mod

    def traceable(self, *, name, run_type, process_inputs, process_outputs):
        def decorator(fn):
            async def wrapped(*args, langsmith_extra=None, **kwargs):
                self.calls += 1
                if self.fail == "before":
                    raise RuntimeError("tracer down before")
                import inspect

                bound = inspect.signature(fn).bind(*args, **kwargs)
                inputs = process_inputs(dict(bound.arguments))
                result = await fn(*args, **kwargs)
                if self.fail == "after":
                    raise RuntimeError("tracer down after")
                self.sent.append({
                    "name": name,
                    "run_type": run_type,
                    "run_id": str(langsmith_extra["run_id"]),
                    "inputs": inputs,
                    "outputs": process_outputs(result),
                })
                return result

            return wrapped

        return decorator


def _enable(monkeypatch, fake: FakeLangsmith):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test-placeholder")
    monkeypatch.setitem(sys.modules, "langsmith", fake.module())


def test_tracing_disabled_unless_flag_and_key(monkeypatch, tracing_off):
    assert tracing.tracing_enabled() is False
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    assert tracing.tracing_enabled() is False, "no API key: still off"
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test-placeholder")
    assert tracing.tracing_enabled() is True
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    assert tracing.tracing_enabled() is False


def test_import_has_no_langsmith_side_effect():
    env = {k: v for k, v in os.environ.items() if not k.startswith("LANGSMITH_")}
    code = (
        "import sys, app.main, app.escales.captain, app.core.llm, app.core.tracing;"
        "assert 'langsmith' not in sys.modules, 'langsmith imported while tracing is off'"
    )
    subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, check=True)


def test_disabled_chat_makes_no_network_call_and_returns_null_trace_id(monkeypatch, no_llm, tracing_off):
    import socket

    def refuse(*_a, **_kw):
        raise AssertionError("network call while tracing is off")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    result = asyncio.run(chat("When is the money captured?", lang="en"))
    assert result["trace_id"] is None


def test_enabled_chat_returns_run_id_and_sends_redacted_inputs(monkeypatch, no_llm):
    fake = FakeLangsmith()
    _enable(monkeypatch, fake)
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "treasurer-secret-123")
    message = "Hi, I am jane.doe@example.com, card 4111 1111 1111 1111, key treasurer-secret-123. When is the money captured?"
    result = asyncio.run(chat(message, lang="en"))
    assert result["reply"]
    assert len(fake.sent) == 1
    run = fake.sent[0]
    assert run["name"] == "captain.chat"
    assert run["run_type"] == "chain"
    assert result["trace_id"] == run["run_id"]
    sent = str(run["inputs"]) + str(run["outputs"])
    assert "jane.doe@example.com" not in sent
    assert "4111 1111 1111 1111" not in sent
    assert "treasurer-secret-123" not in sent
    assert "reader" not in run["inputs"]


def test_enabled_review_returns_run_id_and_keeps_ids(monkeypatch, no_llm):
    fake = FakeLangsmith()
    _enable(monkeypatch, fake)
    reader = ReadOnlyTools(Mock())
    reader._calls["orders.get"] = lambda _: {"id": "ORDER-trace"}

    async def run():
        await ledger.get_ledger().insert_pledge_once({
            "_id": "trace-pledge", "milestone_id": "dep-la-rochelle", "status": "authorized",
            "amount_eur": "5.00", "order_id": "ORDER-trace", "payer_email": "payer@example.com",
        })
        return await review("dep-la-rochelle", reader=reader, lang="en")

    proposal = asyncio.run(run())
    sent = [row for row in fake.sent if row["name"] == "captain.review"]
    assert len(sent) == 1
    assert proposal["trace_id"] == sent[0]["run_id"]
    outputs = sent[0]["outputs"]
    assert outputs["pledge_ids"] == ["trace-pledge"]
    assert outputs["milestone_id"] == "dep-la-rochelle"
    assert outputs["proposal"] == proposal["proposal"]
    assert outputs["pending_authorizations"][0]["amount_eur"] == "5.00"
    assert "payer@example.com" not in str(outputs)


@pytest.mark.parametrize("fail", ["before", "after"])
def test_tracer_failure_never_breaks_the_reply(monkeypatch, no_llm, fail):
    fake = FakeLangsmith(fail=fail)
    _enable(monkeypatch, fake)
    runs = []
    original = tracing.traced("probe", "chain", attach_trace_id=True)

    async def body(value):
        runs.append(value)
        return {"value": value}

    wrapped = original(body)
    result = asyncio.run(wrapped(7))
    assert result["value"] == 7
    assert result["trace_id"] is None
    assert runs == [7], "the function runs exactly once"


def test_function_error_is_not_swallowed(monkeypatch):
    fake = FakeLangsmith()
    _enable(monkeypatch, fake)

    @tracing.traced("probe", "chain")
    async def boom():
        raise ValueError("message is required")

    with pytest.raises(ValueError, match="message is required"):
        asyncio.run(boom())


def test_missing_langsmith_package_falls_back(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test-placeholder")
    monkeypatch.setitem(sys.modules, "langsmith", None)  # import raises ImportError

    @tracing.traced("probe", "chain", attach_trace_id=True)
    async def ok():
        return {"ok": True}

    assert asyncio.run(ok()) == {"ok": True, "trace_id": None}


def test_ask_text_run_is_named_after_the_hop(monkeypatch):
    fake = FakeLangsmith()
    _enable(monkeypatch, fake)
    renamed = {}
    monkeypatch.setattr(llm, "annotate_run", lambda name=None, metadata=None: renamed.update(name=name, meta=metadata))
    monkeypatch.setattr(llm, "has_llm", lambda: True)
    monkeypatch.setattr(llm, "consume_llm_call", lambda *a, **k: True)
    monkeypatch.setattr(llm, "active_providers", lambda order=None: ["openrouter"])

    async def fake_openrouter(*_a, **_kw):
        return llm.LlmResult("hello", "openrouter", "openrouter/free")

    monkeypatch.setattr(llm, "_call_openrouter", fake_openrouter)
    result = asyncio.run(llm.ask_text("ping jane@example.com", client=Mock(), lang="en"))
    assert result.text == "hello"
    assert renamed["name"] == "openrouter/openrouter/free"
    assert renamed["meta"]["ls_model_name"] == "openrouter/free"
    run = fake.sent[0]
    assert run["name"] == "llm.ask_text" and run["run_type"] == "llm"
    assert "client" not in run["inputs"]
    assert "jane@example.com" not in str(run["inputs"])
    assert run["outputs"]["model"] == "openrouter/free"


def test_redact_strips_email_card_and_treasurer_key(monkeypatch):
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "treasurer-secret-123")
    payload = {
        "message": "Mail me at a.b+c@mail.example.org or pay with 5555-5555-5555-4444 key treasurer-secret-123",
        "x-admin-key": "treasurer-secret-123",
        "payer": {"email_address": "payer@example.com", "payer_id": "PAYERX"},
        "contributor_name": "Jane Doe",
        "pledge_id": "pledge-1",
        "amount_eur": "12.50",
        "milestone_id": "dep-ajaccio-corse",
        "order_id": "5O190127TN364715T",
        "authorization_id": "0VF52814937998046",
        "model": "nvidia/nemotron",
        "latency_ms": 12.3,
        "proposal": "capture",
    }
    clean = tracing.redact(payload)
    text = str(clean)
    for secret in ("a.b+c@mail.example.org", "5555-5555-5555-4444", "treasurer-secret-123",
                   "payer@example.com", "PAYERX", "Jane Doe"):
        assert secret not in text
    assert clean["pledge_id"] == "pledge-1"
    assert clean["amount_eur"] == "12.50"
    assert clean["milestone_id"] == "dep-ajaccio-corse"
    assert clean["order_id"] == "5O190127TN364715T"
    assert clean["authorization_id"] == "0VF52814937998046"
    assert clean["model"] == "nvidia/nemotron"
    assert clean["latency_ms"] == 12.3
    assert clean["proposal"] == "capture"


def test_redact_handles_json_prompts():
    prompt = '{"message": "I am bob@example.com", "suggested": {"amount_eur": "20.00", "name": "Bob"}}'
    clean = tracing.redact(prompt)
    assert "bob@example.com" not in clean
    assert "Bob" not in clean
    assert '"amount_eur": "20.00"' in clean


def test_real_langsmith_receives_run_id_and_redacted_inputs(monkeypatch, no_llm):
    langsmith = pytest.importorskip("langsmith")
    from unittest.mock import MagicMock

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test-placeholder")
    client = MagicMock()

    async def run():
        with langsmith.tracing_context(enabled=True, client=client):
            return await chat("Where is the boat? Write to me at jane@example.com", lang="en")

    result = asyncio.run(run())
    created = [c.kwargs for c in client.method_calls if c[0] == "create_run"]
    assert created, "the mocked client received the run; nothing left the process"
    assert str(created[0]["id"]) == result["trace_id"]
    assert created[0]["name"] == "captain.chat"
    assert created[0]["run_type"] == "chain"
    assert "jane@example.com" not in str(created[0]["inputs"])
