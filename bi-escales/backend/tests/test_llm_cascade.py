"""Real LLM cascade. HTTP is mocked. No provider is contacted."""
from __future__ import annotations

import asyncio
import inspect
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import llm
from app.escales import captain
from app.escales.captain import chat, review
from app.escales.milestones import record_evidence
from app.escales.pledges import authorize_pledge, create_pledge, require_pledge, reset_ledger
from app.escales.toolkit_tools import ReadOnlyTools

ENV_FILE = Path(__file__).resolve().parents[2] / ".env.example"
LLM_ENV = (
    "ESCALES_LLM_ENABLED",
    "ESCALES_LLM_NEBIUS_ENABLED",
    "NVIDIA_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENROUTER_MODEL",
    "ANTHROPIC_API_KEY",
    "NEBIUS_API_KEY",
    "NAVIGUIDE_TF_BASE",
    "HELLOASSO_MEMBERSHIP_URL",
    "ESCALES_TOOLKIT_ENABLED",
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    for name in LLM_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ESCALES_STORE", "memory")
    reset_ledger()
    yield
    reset_ledger()


class Spy:
    def __init__(self):
        self.calls = []
        self.n = 0

    def create_authorize_order(self, amount_eur, description, reference_id, idempotency_key=None):
        self.calls.append(("create", idempotency_key))
        self.n += 1
        order_id = f"ORDER{self.n}"
        return {
            "id": order_id,
            "links": [{"rel": "approve", "href": f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}"}],
        }

    def authorize_order(self, order_id):
        self.calls.append(("authorize", order_id))
        return {
            "id": order_id,
            "purchase_units": [{
                "payments": {"authorizations": [{"id": f"AUTH-{order_id}", "expiration_time": "2026-12-01T00:00:00Z"}]},
            }],
        }

    def capture_authorization(self, authorization_id, final=True):
        self.calls.append(("capture", authorization_id))
        return {"status": "COMPLETED"}

    def void_authorization(self, authorization_id):
        self.calls.append(("void", authorization_id))
        return {}

    def get_order(self, order_id):
        self.calls.append(("orders.get", order_id))
        return {"id": order_id, "status": "APPROVED"}

    def get_authorization(self, authorization_id):
        self.calls.append(("authorizations.get", authorization_id))
        return {"id": authorization_id, "status": "CREATED"}


def _enable(*names: str, nebius: str | None = None) -> None:
    import os

    os.environ["ESCALES_LLM_ENABLED"] = "1"
    keys = {
        "nim": ("NVIDIA_API_KEY", "test-nvidia-key"),
        "openrouter": ("OPENROUTER_API_KEY", "test-openrouter-key"),
        "anthropic": ("ANTHROPIC_API_KEY", "test-anthropic-key"),
        "tokenfactory": ("NEBIUS_API_KEY", "test-nebius-key"),
    }
    for name in names:
        var, value = keys[name]
        os.environ[var] = value
    if nebius is not None:
        os.environ["ESCALES_LLM_NEBIUS_ENABLED"] = nebius


def _openai(text: str, model: str, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "model": model,
            "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        },
    )


def _anthropic(text: str, model: str = llm.ANTHROPIC_MODEL, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json={"model": model, "content": [{"type": "text", "text": text}]},
    )


def _fail(status: int) -> httpx.Response:
    return httpx.Response(status, json={"error": {"message": "unavailable"}})


def _transport(script: dict[str, list[httpx.Response]]):
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        seen.append({
            "url": str(request.url),
            "host": request.url.host,
            "model": body.get("model"),
            "body": body,
            "authorization": request.headers.get("authorization"),
            "x-api-key": request.headers.get("x-api-key"),
            "anthropic-version": request.headers.get("anthropic-version"),
            "raw": request.content.decode(),
        })
        queue = script.get(request.url.host)
        if not queue:
            raise AssertionError(f"unexpected host {request.url.host}")
        return queue.pop(0)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=llm.TIMEOUT)
    return seen, client


def test_cascade_order_puts_nebius_last_and_rules_after_it():
    assert llm.CASCADE == ("nim", "openrouter", "anthropic", "tokenfactory", "rules")
    assert llm.NIM_MODEL == "openai/gpt-oss-20b"
    source = inspect.getsource(captain)
    assert "capture_authorization" not in source
    assert "void_authorization" not in source
    assert "paypal_client" not in source
    module = Path(llm.__file__).read_text(encoding="utf-8")
    assert "capture_authorization" not in module
    assert "sk-" not in module
    assert "nvapi-" not in module


def test_env_example_lists_flags_and_empty_keys():
    lines = [line.strip() for line in ENV_FILE.read_text(encoding="utf-8").splitlines()]
    assert "ESCALES_LLM_ENABLED=" in lines
    assert "ESCALES_LLM_NEBIUS_ENABLED=false" in lines
    for name in ("NVIDIA_API_KEY", "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "ANTHROPIC_API_KEY", "NEBIUS_API_KEY"):
        assert f"{name}=" in lines
    for line in lines:
        if line.split("=", 1)[0] in {"NVIDIA_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "NEBIUS_API_KEY"}:
            assert line.endswith("=")
            assert line.split("=", 1)[1] == ""


def test_master_flag_off_does_not_open_http(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    monkeypatch.setenv("NEBIUS_API_KEY", "test-nebius-key")
    monkeypatch.setenv("ESCALES_LLM_NEBIUS_ENABLED", "true")
    assert llm.llm_enabled() is False
    assert llm.has_llm() is False
    assert llm.active_providers() == ["nim", "tokenfactory"]

    def boom():
        raise AssertionError("HTTP client opened")

    monkeypatch.setattr(llm, "_client", boom)

    async def body():
        with pytest.raises(RuntimeError, match="No LLM configured"):
            await llm.ask_text("bonjour")

    asyncio.run(body())


def test_has_llm_needs_a_key_and_ignores_blank_values(monkeypatch):
    monkeypatch.setenv("ESCALES_LLM_ENABLED", "1")
    assert llm.has_llm() is False
    monkeypatch.setenv("NVIDIA_API_KEY", "   ")
    assert llm.active_providers() == []
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    assert llm.has_llm() is True
    assert llm.active_providers() == ["nim"]


def test_nebius_stays_off_unless_its_flag_is_truthy(monkeypatch):
    monkeypatch.setenv("ESCALES_LLM_ENABLED", "1")
    monkeypatch.setenv("NEBIUS_API_KEY", "test-nebius-key")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    assert llm.nebius_enabled() is False
    assert llm.active_providers() == ["nim"]
    monkeypatch.setenv("ESCALES_LLM_NEBIUS_ENABLED", "false")
    assert llm.active_providers() == ["nim"]
    monkeypatch.setenv("ESCALES_LLM_NEBIUS_ENABLED", "0")
    assert "tokenfactory" not in llm.active_providers()
    monkeypatch.setenv("ESCALES_LLM_NEBIUS_ENABLED", "true")
    assert llm.active_providers() == ["nim", "tokenfactory"]
    monkeypatch.delenv("NVIDIA_API_KEY")
    assert llm.active_providers() == ["tokenfactory"]
    assert llm.has_llm() is True


def test_configured_providers_keep_nim_openrouter_anthropic_nebius_order(monkeypatch):
    monkeypatch.setenv("ESCALES_LLM_ENABLED", "1")
    monkeypatch.setenv("ESCALES_LLM_NEBIUS_ENABLED", "yes")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("NEBIUS_API_KEY", "test-nebius-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    assert llm.active_providers() == ["nim", "openrouter", "anthropic", "tokenfactory"]


def test_nim_answers_first_with_gpt_oss_20b(monkeypatch):
    _enable("nim", "openrouter", "anthropic", "tokenfactory", nebius="true")
    seen, client = _transport({
        "integrate.api.nvidia.com": [_openai("Rapport NIM.", llm.NIM_MODEL)],
        "openrouter.ai": [_openai("ne doit pas partir", "openai/gpt-4o-mini")],
    })

    async def body():
        result = await llm.ask_text("preuve", system="systeme", max_tokens=500, client=client)
        assert result.text == "Rapport NIM."
        assert result.provider == "nim"
        assert result.model == "openai/gpt-oss-20b"
        assert [item["host"] for item in seen] == ["integrate.api.nvidia.com"]
        call = seen[0]
        assert call["url"] == llm.NVIDIA_URL
        assert call["model"] == "openai/gpt-oss-20b"
        assert call["authorization"] == "Bearer test-nvidia-key"
        assert call["x-api-key"] is None
        assert "test-nvidia-key" not in call["raw"]
        assert call["body"]["temperature"] == 0.6
        assert call["body"]["top_p"] == 0.7
        assert call["body"]["reasoning_effort"] == "low"
        assert call["body"]["chat_template_kwargs"] == {"thinking": False}
        assert call["body"]["max_tokens"] == 500
        assert call["body"]["messages"][0] == {"role": "system", "content": "systeme"}
        await client.aclose()

    asyncio.run(body())


def test_fallback_order_is_openrouter_then_anthropic_then_nebius(monkeypatch):
    _enable("nim", "openrouter", "anthropic", "tokenfactory", nebius="true")
    monkeypatch.setenv("OPENROUTER_MODEL", "meta/example-small")
    seen, client = _transport({
        "integrate.api.nvidia.com": [_fail(503)],
        "openrouter.ai": [_fail(429)],
        "api.anthropic.com": [_fail(500)],
        "api.tokenfactory.nebius.com": [_openai("Rapport Nebius.", llm.TOKENFACTORY_MODEL)],
    })

    async def body():
        result = await llm.ask_text("preuve", client=client)
        assert result.provider == "tokenfactory"
        assert result.model == llm.TOKENFACTORY_MODEL
        assert result.text == "Rapport Nebius."
        assert [item["host"] for item in seen] == [
            "integrate.api.nvidia.com",
            "openrouter.ai",
            "api.anthropic.com",
            "api.tokenfactory.nebius.com",
        ]
        assert seen[1]["model"] == "meta/example-small"
        assert seen[1]["authorization"] == "Bearer test-openrouter-key"
        assert seen[1]["body"]["temperature"] == 0.4
        assert seen[2]["model"] == llm.ANTHROPIC_MODEL
        assert seen[2]["x-api-key"] == "test-anthropic-key"
        assert seen[2]["authorization"] is None
        assert seen[2]["anthropic-version"] == "2023-06-01"
        assert seen[2]["body"]["temperature"] == 0
        assert seen[2]["body"]["system"]
        assert "test-anthropic-key" not in seen[2]["raw"]
        assert seen[3]["url"] == "https://api.tokenfactory.nebius.com/v1/chat/completions"
        assert seen[3]["authorization"] == "Bearer test-nebius-key"
        assert seen[3]["body"]["reasoning_effort"] == "none"
        assert seen[3]["body"]["chat_template_kwargs"] == {"enable_thinking": False}
        assert "test-nebius-key" not in seen[3]["raw"]
        await client.aclose()

    asyncio.run(body())


def test_nebius_is_not_called_when_its_flag_is_off(monkeypatch):
    _enable("nim", "openrouter", "anthropic", "tokenfactory", nebius="false")
    seen, client = _transport({
        "integrate.api.nvidia.com": [_fail(503)],
        "openrouter.ai": [_openai("", "openai/gpt-4o-mini")],
        "api.anthropic.com": [httpx.Response(200, content=b"not-json")],
        "api.tokenfactory.nebius.com": [_openai("ne doit pas partir", llm.TOKENFACTORY_MODEL)],
    })

    async def body():
        with pytest.raises(RuntimeError, match="exhausted"):
            await llm.ask_text("preuve", client=client)
        assert [item["host"] for item in seen] == [
            "integrate.api.nvidia.com",
            "openrouter.ai",
            "api.anthropic.com",
        ]
        await client.aclose()

    asyncio.run(body())


def test_openrouter_answers_when_nim_returns_only_a_think_block():
    _enable("nim", "openrouter")
    seen, client = _transport({
        "integrate.api.nvidia.com": [_openai("<think>secret plan</think>", llm.NIM_MODEL)],
        "openrouter.ai": [_openai("<think>brouillon</think>Rapport OpenRouter.", "openai/gpt-4o-mini")],
    })

    async def body():
        result = await llm.ask_text("preuve", client=client)
        assert result.provider == "openrouter"
        assert result.model == "openai/gpt-4o-mini"
        assert result.text == "Rapport OpenRouter."
        assert [item["host"] for item in seen] == ["integrate.api.nvidia.com", "openrouter.ai"]
        await client.aclose()

    asyncio.run(body())


def test_anthropic_text_blocks_and_echoed_model():
    _enable("anthropic")
    seen, client = _transport({
        "api.anthropic.com": [_anthropic("Rapport Claude.", model="claude-haiku-4-5-20251001")],
    })

    async def body():
        result = await llm.ask_text("preuve", client=client)
        assert result.provider == "anthropic"
        assert result.model == "claude-haiku-4-5-20251001"
        assert result.text == "Rapport Claude."
        assert seen[0]["body"]["messages"] == [{"role": "user", "content": "preuve"}]
        await client.aclose()

    asyncio.run(body())


def test_missing_keys_are_skipped():
    _enable("openrouter")
    seen, client = _transport({
        "openrouter.ai": [_openai("Seul OpenRouter.", "openai/gpt-4o-mini")],
    })

    async def body():
        result = await llm.ask_text("preuve", client=client)
        assert result.provider == "openrouter"
        assert [item["host"] for item in seen] == ["openrouter.ai"]
        await client.aclose()

    asyncio.run(body())


def test_captain_review_exposes_nim_and_never_captures(monkeypatch):
    _enable("nim", "tokenfactory", nebius="true")
    seen_box: dict = {}

    def factory():
        seen, client = _transport({
            "integrate.api.nvidia.com": [_openai("Le modele voudrait annuler.", llm.NIM_MODEL)],
        })
        seen_box["seen"] = seen
        return client

    monkeypatch.setattr(llm, "_client", factory)

    async def body():
        spy = Spy()
        pledge = await create_pledge(
            amount_eur="20.00",
            description="20 milles",
            milestone_id="dep-mayotte",
            client=spy,
            client_key="llm-1",
        )
        await authorize_pledge(pledge["_id"], spy)
        await record_evidence("dep-mayotte", met=True, facts={"port": "Mayotte"})
        result = await review("dep-mayotte", reader=ReadOnlyTools(spy))
        assert result["proposal"] == "capture"
        assert result["model_source"] == {"provider": "nim", "model": "openai/gpt-oss-20b"}
        assert "annuler" in result["report"]
        assert seen_box["seen"][0]["host"] == "integrate.api.nvidia.com"
        assert len(seen_box["seen"]) == 1
        names = [call[0] for call in spy.calls]
        assert "capture" not in names
        assert "void" not in names
        assert "orders.get" in names
        assert (await require_pledge(pledge["_id"]))["status"] == "authorized"

    asyncio.run(body())


def test_captain_strips_invented_figures_and_keeps_the_source(monkeypatch):
    _enable("nim")
    monkeypatch.setattr(
        llm,
        "_client",
        lambda: _transport({
            "integrate.api.nvidia.com": [_openai("999 spectateurs au port.", llm.NIM_MODEL)],
        })[1],
    )

    async def body():
        await record_evidence("dep-mayotte", met=True, facts={"port": "Mayotte"})
        result = await review("dep-mayotte", reader=None)
        assert "999" not in result["report"]
        assert "[?]" in result["justification"]
        assert result["proposal"] == "capture"
        assert result["model_source"] == {"provider": "nim", "model": "openai/gpt-oss-20b"}

    asyncio.run(body())


def test_captain_chat_exposes_the_model_and_does_not_order(monkeypatch):
    _enable("openrouter")
    monkeypatch.setenv(
        "HELLOASSO_MEMBERSHIP_URL",
        "https://www.helloasso.com/associations/blue-intelligence/adhesions/membre",
    )
    monkeypatch.setattr(
        llm,
        "_client",
        lambda: _transport({
            "openrouter.ai": [_openai("Promesse suggeree, sans debit.", "openai/gpt-4o-mini")],
        })[1],
    )

    async def body():
        result = await chat("Je veux parrainer 20 milles près de Mayotte")
        assert result["model_source"] == {"provider": "openrouter", "model": "openai/gpt-4o-mini"}
        assert result["membership_url"] in result["reply"]
        assert result["suggested_pledge"]["amount_eur"] == "20.00"
        assert result["suggested_pledge"]["intent"] == "AUTHORIZE"
        assert "order_id" not in result

    asyncio.run(body())


def test_captain_uses_rules_when_the_flag_is_off(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    monkeypatch.setenv("NEBIUS_API_KEY", "test-nebius-key")

    def boom():
        raise AssertionError("HTTP client opened")

    monkeypatch.setattr(llm, "_client", boom)

    async def body():
        await record_evidence("dep-mayotte", met=False, facts={"port": "Mayotte"})
        result = await review("dep-mayotte", reader=None)
        assert result["proposal"] == "void"
        assert result["model_source"] == {"provider": "rules", "model": ""}
        assert "simulation" in result["report"]
        spoken = await chat("Parraine 20 milles près de Mayotte")
        assert spoken["model_source"] == {"provider": "rules", "model": ""}
        assert spoken["suggested_pledge"]["amount_eur"] == "20.00"

    asyncio.run(body())


def test_captain_uses_rules_when_every_provider_fails(monkeypatch):
    _enable("nim", "tokenfactory", nebius="false")
    seen_box: dict = {}

    def factory():
        seen, client = _transport({
            "integrate.api.nvidia.com": [_fail(401)],
            "api.tokenfactory.nebius.com": [_openai("ne doit pas partir", llm.TOKENFACTORY_MODEL)],
        })
        seen_box["seen"] = seen
        return client

    monkeypatch.setattr(llm, "_client", factory)

    async def body():
        await record_evidence("dep-mayotte", met=True, facts={"port": "Mayotte"})
        result = await review("dep-mayotte", reader=None)
        assert result["model_source"] == {"provider": "rules", "model": ""}
        assert result["proposal"] == "capture"
        assert "Proposition" in result["report"]
        assert [item["host"] for item in seen_box["seen"]] == ["integrate.api.nvidia.com"]

    asyncio.run(body())
