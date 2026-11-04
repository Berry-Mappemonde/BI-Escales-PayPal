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
    "NIM_MODEL",
    "NIM_TEMPERATURE",
    "NIM_MAX_TOKENS",
    "NIM_TOP_P",
    "NIM_REASONING",
    "NIM_EXTRA_BODY",
    "NIM_FALLBACK_MODEL",
    "ESCALES_LLM_TIMEOUT_S",
    "ESCALES_LLM_TIMEOUT_NIM_S",
    "ESCALES_LLM_TIMEOUT_NIM_FALLBACK_S",
    "ESCALES_LLM_TIMEOUT_OPENROUTER_S",
    "ESCALES_LLM_TIMEOUT_ANTHROPIC_S",
    "ESCALES_LLM_TIMEOUT_TOKENFACTORY_S",
    "ESCALES_ENV",
    "ESCALES_RATE_LIMIT_ENABLED",
    "ESCALES_LLM_DAILY_CAP",
    "ESCALES_CAPTAIN_RATE_PER_MINUTE",
    "ESCALES_CAPTAIN_RATE_PER_DAY",
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    for name in LLM_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_NIM_GAP_S", "0")
    reset_ledger()
    llm.reset_llm_budget()
    llm.reset_nim_pace()
    yield
    reset_ledger()
    llm.reset_llm_budget()
    llm.reset_nim_pace()


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
    assert llm.CASCADE == (
        "nim", "nim_fallback", "openrouter", "omniroute", "anthropic", "tokenfactory", "rules",
    )
    assert llm.NIM_MODEL == llm.NIM_MODEL_DEFAULT == "private/nvidia/nemotron-3.5-super-120b-a12b"
    assert llm.NIM_FALLBACK_MODEL_DEFAULT == "nvidia/nemotron-3.5-lightning-30b-a3b"
    module = Path(llm.__file__).read_text(encoding="utf-8")
    assert '{"thinking": False}' not in module
    assert "enable_thinking" in module
    assert "29" not in captain._report_system("lorient")
    assert "29" not in captain._chat_system("fr")
    assert "reauthor" not in captain._chat_system("en").lower()
    source = inspect.getsource(captain)
    assert "capture_authorization" not in source
    assert "void_authorization" not in source
    assert "paypal_client" not in source
    assert "capture_authorization" not in module
    assert "sk-" not in module
    assert "nvapi-" not in module


def test_env_example_lists_flags_and_empty_keys():
    lines = [line.strip() for line in ENV_FILE.read_text(encoding="utf-8").splitlines()]
    assert "ESCALES_LLM_ENABLED=" in lines
    assert "ESCALES_LLM_NEBIUS_ENABLED=false" in lines
    assert "ESCALES_ENV=development" in lines
    for name in (
        "NVIDIA_API_KEY", "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "ANTHROPIC_API_KEY", "NEBIUS_API_KEY",
        "NIM_MODEL", "NIM_TEMPERATURE", "NIM_MAX_TOKENS", "NIM_TOP_P", "NIM_REASONING", "NIM_EXTRA_BODY",
        "NIM_FALLBACK_MODEL", "ESCALES_LLM_TIMEOUT_NIM_S", "ESCALES_LLM_TIMEOUT_NIM_FALLBACK_S",
        "ESCALES_ENV", "ESCALES_RATE_LIMIT_ENABLED", "ESCALES_LLM_DAILY_CAP",
        "ESCALES_CAPTAIN_RATE_PER_MINUTE", "ESCALES_CAPTAIN_RATE_PER_DAY",
    ):
        assert any(line.startswith(f"{name}=") for line in lines)
    assert "ESCALES_LLM_TIMEOUT_S=10" in lines
    assert "NIM_TEMPERATURE=" in lines
    assert "NIM_MODEL=private/nvidia/nemotron-3.5-super-120b-a12b" in lines
    assert "NIM_FALLBACK_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b" in lines
    assert "NIM_TOP_P=0.95" in lines
    assert "NIM_MAX_TOKENS=400" in lines
    assert "NIM_REASONING=none" in lines
    assert "ESCALES_LLM_TIMEOUT_NIM_FALLBACK_S=10" in lines
    joined = "\n".join(lines)
    assert "enable_thinking" in joined
    extra = next(line for line in lines if line.startswith("NIM_EXTRA_BODY="))
    assert "guided_json" not in extra
    assert "nvext" not in extra
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
    assert llm.active_providers() == ["nim", "nim_fallback", "tokenfactory"]

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
    assert llm.active_providers() == ["nim", "nim_fallback"]
    monkeypatch.setenv("NIM_FALLBACK_MODEL", "")
    assert llm.active_providers() == ["nim"]


def test_nebius_stays_off_unless_its_flag_is_truthy(monkeypatch):
    monkeypatch.setenv("ESCALES_LLM_ENABLED", "1")
    monkeypatch.setenv("NEBIUS_API_KEY", "test-nebius-key")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    assert llm.nebius_enabled() is False
    assert llm.active_providers() == ["nim", "nim_fallback"]
    monkeypatch.setenv("ESCALES_LLM_NEBIUS_ENABLED", "false")
    assert llm.active_providers() == ["nim", "nim_fallback"]
    monkeypatch.setenv("ESCALES_LLM_NEBIUS_ENABLED", "0")
    assert "tokenfactory" not in llm.active_providers()
    monkeypatch.setenv("ESCALES_LLM_NEBIUS_ENABLED", "true")
    assert llm.active_providers() == ["nim", "nim_fallback", "tokenfactory"]
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
    assert llm.active_providers() == [
        "nim", "nim_fallback", "openrouter", "anthropic", "tokenfactory",
    ]


def test_nim_answers_first_with_the_benchmarked_model(monkeypatch):
    _enable("nim", "openrouter", "anthropic", "tokenfactory", nebius="true")
    seen, client = _transport({
        "integrate.api.nvidia.com": [_openai("Rapport NIM.", llm.NIM_MODEL)],
        "openrouter.ai": [_openai("ne doit pas partir", "openai/gpt-4o-mini")],
    })

    async def body():
        result = await llm.ask_text("preuve", system="systeme", max_tokens=500, client=client)
        assert result.text == "Rapport NIM."
        assert result.provider == "nim"
        assert result.model == llm.NIM_MODEL_DEFAULT
        assert [item["host"] for item in seen] == ["integrate.api.nvidia.com"]
        call = seen[0]
        assert call["url"] == llm.NVIDIA_URL
        assert call["model"] == llm.NIM_MODEL_DEFAULT
        assert call["authorization"] == "Bearer test-nvidia-key"
        assert call["x-api-key"] is None
        assert "test-nvidia-key" not in call["raw"]
        assert "temperature" not in call["body"]
        assert "top_p" not in call["body"]
        assert "reasoning_effort" not in call["body"]
        assert call["body"]["chat_template_kwargs"] == {"enable_thinking": False}
        assert "thinking" not in call["body"]["chat_template_kwargs"]
        assert "guided_json" not in call["body"]
        assert "nvext" not in call["body"]
        assert call["body"]["max_tokens"] == 400
        assert call["body"]["messages"][0] == {"role": "system", "content": "systeme"}
        await client.aclose()

    asyncio.run(body())


def test_fallback_order_is_openrouter_then_anthropic_then_nebius(monkeypatch):
    _enable("nim", "openrouter", "anthropic", "tokenfactory", nebius="true")
    monkeypatch.setenv("OPENROUTER_MODEL", "meta/example-small")
    seen, client = _transport({
        "integrate.api.nvidia.com": [_fail(503), _fail(503)],
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
            "integrate.api.nvidia.com",
            "openrouter.ai",
            "api.anthropic.com",
            "api.tokenfactory.nebius.com",
        ]
        assert seen[0]["model"] == llm.NIM_MODEL_DEFAULT
        assert seen[1]["model"] == llm.NIM_FALLBACK_MODEL_DEFAULT
        assert seen[2]["model"] == "meta/example-small"
        assert seen[2]["authorization"] == "Bearer test-openrouter-key"
        assert seen[2]["body"]["temperature"] == 0.4
        assert seen[3]["model"] == llm.ANTHROPIC_MODEL
        assert seen[3]["x-api-key"] == "test-anthropic-key"
        assert seen[3]["authorization"] is None
        assert seen[3]["anthropic-version"] == "2023-06-01"
        assert seen[3]["body"]["temperature"] == 0
        assert seen[3]["body"]["system"]
        assert "test-anthropic-key" not in seen[3]["raw"]
        assert seen[4]["url"] == "https://api.tokenfactory.nebius.com/v1/chat/completions"
        assert seen[4]["authorization"] == "Bearer test-nebius-key"
        assert seen[4]["body"]["reasoning_effort"] == "none"
        assert seen[4]["body"]["chat_template_kwargs"] == {"enable_thinking": False}
        assert "test-nebius-key" not in seen[4]["raw"]
        await client.aclose()

    asyncio.run(body())


def test_nebius_is_not_called_when_its_flag_is_off(monkeypatch):
    _enable("nim", "openrouter", "anthropic", "tokenfactory", nebius="false")
    seen, client = _transport({
        "integrate.api.nvidia.com": [_fail(503), _fail(503)],
        "openrouter.ai": [_openai("", "openai/gpt-4o-mini")],
        "api.anthropic.com": [httpx.Response(200, content=b"not-json")],
        "api.tokenfactory.nebius.com": [_openai("ne doit pas partir", llm.TOKENFACTORY_MODEL)],
    })

    async def body():
        with pytest.raises(RuntimeError, match="exhausted"):
            await llm.ask_text("preuve", client=client)
        assert [item["host"] for item in seen] == [
            "integrate.api.nvidia.com",
            "integrate.api.nvidia.com",
            "openrouter.ai",
            "api.anthropic.com",
        ]
        await client.aclose()

    asyncio.run(body())


def test_openrouter_answers_when_nim_returns_only_a_think_block():
    _enable("nim", "openrouter")
    seen, client = _transport({
        "integrate.api.nvidia.com": [
            _openai("<think>secret plan</think>", llm.NIM_MODEL),
            _openai("<think>encore</think>", llm.NIM_FALLBACK_MODEL_DEFAULT),
        ],
        "openrouter.ai": [_openai("<think>brouillon</think>Rapport OpenRouter.", "openai/gpt-4o-mini")],
    })

    async def body():
        result = await llm.ask_text("preuve", client=client)
        assert result.provider == "openrouter"
        assert result.model == "openai/gpt-4o-mini"
        assert result.text == "Rapport OpenRouter."
        assert [item["host"] for item in seen] == [
            "integrate.api.nvidia.com",
            "integrate.api.nvidia.com",
            "openrouter.ai",
        ]
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
    seen_box: dict = {"narrative": None}

    def factory():
        seen, client = _transport({
            "integrate.api.nvidia.com": [_openai("Le modele voudrait annuler.", llm.NIM_MODEL)],
        })
        if seen_box["narrative"] is None:
            seen_box["narrative"] = seen
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
        assert result["model_source"] == {"provider": "nim", "model": llm.NIM_MODEL_DEFAULT}
        assert "annuler" in result["report"]
        assert "Mayotte" in result["report"]
        assert "Dep-Mayotte" not in result["report"]
        assert "dep-" not in result["report"].lower()
        narrative = seen_box["narrative"]
        assert narrative[0]["body"]["temperature"] == 0.2
        sentences = [part for part in result["report"].replace("!", ".").replace("?", ".").split(".") if part.strip()]
        assert 2 <= len(sentences) <= 3
        assert narrative[0]["host"] == "integrate.api.nvidia.com"
        assert len(narrative) == 1
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
        assert "[?]" not in result["justification"]
        assert result["proposal"] == "capture"
        assert result["model_source"] == {"provider": "nim", "model": llm.NIM_MODEL_DEFAULT}

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
            "integrate.api.nvidia.com": [_fail(401), _fail(401)],
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
        assert result["report"].startswith("L'escale Mayotte est atteinte")
        assert [item["host"] for item in seen_box["seen"]] == [
            "integrate.api.nvidia.com",
            "integrate.api.nvidia.com",
        ]

    asyncio.run(body())


def test_nim_http_429_retries_the_same_model_once(monkeypatch):
    _enable("nim")
    pauses = []

    async def fake_sleep(seconds):
        pauses.append(seconds)

    monkeypatch.setattr(llm.asyncio, "sleep", fake_sleep)
    assert 0.5 <= llm.nim_rate_limit_pause() <= 1
    seen, client = _transport({
        "integrate.api.nvidia.com": [
            _fail(429),
            _openai("Rapport tenu.", llm.nim_model()),
        ],
    })

    async def body():
        result = await llm.ask_text("preuve", client=client)
        assert result.text == "Rapport tenu."
        assert result.provider == "nim"
        assert [item["model"] for item in seen] == [llm.NIM_MODEL_DEFAULT, llm.NIM_MODEL_DEFAULT]
        assert pauses == [llm.nim_rate_limit_pause()]
        await client.aclose()

    asyncio.run(body())

    pauses.clear()
    seen, client = _transport({
        "integrate.api.nvidia.com": [
            _fail(429),
            _fail(429),
            _openai("Secours.", llm.nim_fallback_model()),
        ],
    })

    async def fallback():
        result = await llm.ask_text("preuve", client=client)
        assert result.text == "Secours."
        assert result.provider == "nim_fallback"
        assert "http_429" in result.reason
        assert [item["model"] for item in seen] == [
            llm.NIM_MODEL_DEFAULT,
            llm.NIM_MODEL_DEFAULT,
            llm.NIM_FALLBACK_MODEL_DEFAULT,
        ]
        assert pauses == [llm.nim_rate_limit_pause()]
        await client.aclose()

    asyncio.run(fallback())


def test_nim_calls_are_spaced_by_more_than_one_second(monkeypatch):
    _enable("nim")
    monkeypatch.delenv("ESCALES_NIM_GAP_S", raising=False)
    assert llm.nim_call_gap() > 1
    clock = {"t": 1000.0}
    pauses = []

    def fake_mono():
        return clock["t"]

    async def fake_sleep(seconds):
        pauses.append(seconds)
        clock["t"] += seconds

    monkeypatch.setattr(llm.time, "monotonic", fake_mono)
    monkeypatch.setattr(llm.asyncio, "sleep", fake_sleep)
    llm.reset_nim_pace()
    seen, client = _transport({
        "integrate.api.nvidia.com": [
            _openai("Un.", llm.nim_model()),
            _openai("Deux.", llm.nim_model()),
        ],
    })

    async def body():
        first = await llm.ask_text("un", client=client)
        second = await llm.ask_text("deux", client=client)
        assert first.text == "Un."
        assert second.text == "Deux."
        assert [item["model"] for item in seen] == [llm.NIM_MODEL_DEFAULT, llm.NIM_MODEL_DEFAULT]
        assert pauses == [llm.NIM_CALL_GAP_S]
        await client.aclose()

    asyncio.run(body())


def test_nim_params_come_from_the_environment(monkeypatch):
    _enable("nim")
    monkeypatch.setenv("NIM_MODEL", "nvidia/benchmark-model")
    monkeypatch.setenv("NIM_TEMPERATURE", "0.15")
    monkeypatch.setenv("NIM_MAX_TOKENS", "128")
    monkeypatch.setenv("NIM_TOP_P", "0.5")
    monkeypatch.setenv("NIM_REASONING", "none")
    monkeypatch.setenv("NIM_EXTRA_BODY", '{"seed": 7, "chat_template_kwargs": {"thinking": false}}')
    seen, client = _transport({
        "integrate.api.nvidia.com": [_openai("Rapport.", "nvidia/benchmark-model")],
    })

    async def body():
        result = await llm.ask_text("preuve", max_tokens=500, temperature=0.2, client=client)
        body_json = seen[0]["body"]
        assert body_json["model"] == "nvidia/benchmark-model"
        assert body_json["temperature"] == 0.15
        assert body_json["max_tokens"] == 128
        assert body_json["top_p"] == 0.5
        assert "reasoning_effort" not in body_json
        assert body_json["seed"] == 7
        assert body_json["messages"][1]["content"] == "preuve"
        assert result.provider == "nim"
        await client.aclose()

    asyncio.run(body())


def test_invalid_nim_extra_body_is_ignored(monkeypatch):
    _enable("nim")
    monkeypatch.setenv("NIM_EXTRA_BODY", "not-json")
    seen, client = _transport({
        "integrate.api.nvidia.com": [_openai("Rapport.", llm.nim_model())],
    })

    async def body():
        await llm.ask_text("preuve", client=client)
        assert "seed" not in seen[0]["body"]
        assert seen[0]["model"] == llm.NIM_MODEL_DEFAULT
        assert seen[0]["body"]["chat_template_kwargs"] == {"enable_thinking": False}
        await client.aclose()

    asyncio.run(body())


def test_provider_timeout_defaults_to_ten_seconds_and_is_configurable(monkeypatch):
    assert llm.provider_timeout_seconds("nim") == 20.0
    assert llm.provider_timeout_seconds("nim_fallback") == 10.0
    assert llm.provider_timeout_seconds("nim_fallback") == 10
    assert 8 <= llm.provider_timeout_seconds("openrouter") <= 10
    monkeypatch.setenv("ESCALES_LLM_TIMEOUT_S", "9")
    monkeypatch.setenv("ESCALES_LLM_TIMEOUT_NIM_S", "8")
    assert llm.provider_timeout_seconds("nim") == 8
    assert llm.provider_timeout_seconds("nim_fallback") == 10
    assert llm.provider_timeout_seconds("anthropic") == 9
    monkeypatch.setenv("ESCALES_LLM_TIMEOUT_NIM_FALLBACK_S", "7")
    assert llm.provider_timeout_seconds("nim_fallback") == 7
    timeout = llm.provider_timeout("nim")
    assert timeout.read == 8


def test_nim_fallback_answers_before_openrouter():
    _enable("nim", "openrouter")
    calls = []

    class FakeClient:
        async def post(self, url, headers=None, json=None, timeout=None):
            calls.append({
                "host": url.host if hasattr(url, "host") else str(url),
                "model": json["model"],
                "read": timeout.read,
                "guided": "guided_json" in json,
                "nvext": "nvext" in json,
            })
            if len(calls) == 1:
                return httpx.Response(503, json={"error": {"message": "slow"}})
            return httpx.Response(200, json={
                "model": json["model"],
                "choices": [{"message": {"content": "fallback ok"}}],
            })

        async def aclose(self):
            return None

    async def body():
        result = await llm.ask_text("preuve", client=FakeClient())
        assert result.text == "fallback ok"
        assert result.provider == "nim_fallback"
        assert result.model == llm.NIM_FALLBACK_MODEL_DEFAULT
        assert llm.NIM_MODEL_DEFAULT in result.reason
        assert "http_503" in result.reason
        assert llm.NIM_FALLBACK_MODEL_DEFAULT in result.reason
        assert "Bearer" not in result.reason
        assert "nvapi" not in result.reason
        assert len(calls) == 2
        assert calls[0]["model"] == llm.NIM_MODEL_DEFAULT
        assert calls[0]["read"] == 20
        assert calls[1]["model"] == llm.NIM_FALLBACK_MODEL_DEFAULT
        assert calls[1]["read"] == 10
        assert calls[0]["guided"] is False
        assert calls[1]["nvext"] is False

    asyncio.run(body())


def test_global_extra_body_cannot_carry_guided_json(monkeypatch):
    _enable("nim")
    monkeypatch.setenv(
        "NIM_EXTRA_BODY",
        '{"guided_json": {"type": "object"}, "nvext": {"guided_json": {"type": "object"}}, "seed": 3}',
    )
    seen, client = _transport({
        "integrate.api.nvidia.com": [_openai("Rapport.", llm.NIM_MODEL_DEFAULT)],
    })

    async def body():
        await llm.ask_text("preuve", client=client)
        body_json = seen[0]["body"]
        assert "guided_json" not in body_json
        assert "nvext" not in body_json
        assert body_json["seed"] == 3
        assert body_json["chat_template_kwargs"] == {"enable_thinking": False}
        assert "reasoning_effort" not in body_json
        assert "nvext" not in body_json
        await client.aclose()

    asyncio.run(body())


def test_each_call_sends_its_own_timeout(monkeypatch):
    _enable("nim")
    captured = {}

    class FakeClient:
        async def post(self, url, headers=None, json=None, timeout=None):
            captured["timeout"] = timeout
            captured["url"] = url
            return httpx.Response(200, json={
                "model": llm.nim_model(),
                "choices": [{"message": {"content": "ok"}}],
            })

        async def aclose(self):
            return None

    async def body():
        result = await llm.ask_text("preuve", client=FakeClient())
        assert result.text == "ok"
        assert captured["timeout"].read == 20

    asyncio.run(body())


def test_ask_json_parses_a_fenced_object():
    _enable("nim")
    seen, client = _transport({
        "integrate.api.nvidia.com": [_openai(
            '```json\n{"proposal":"wait","reason":"ok"}\n```',
            llm.NIM_FALLBACK_MODEL_DEFAULT,
        )],
    })

    async def body():
        parsed = await llm.ask_json("Return JSON", client=client)
        assert parsed.data == {"proposal": "wait", "reason": "ok"}
        assert parsed.provider == "nim_fallback"
        assert parsed.model == llm.NIM_FALLBACK_MODEL_DEFAULT
        body_json = seen[0]["body"]
        assert body_json["model"] == llm.NIM_FALLBACK_MODEL_DEFAULT
        assert body_json["temperature"] == 0
        assert "top_p" not in body_json
        assert "reasoning_effort" not in body_json
        assert "nvext" not in body_json
        assert body_json["guided_json"] == llm.ADVISORY_PROPOSAL_SCHEMA
        assert body_json["guided_json"]["properties"]["proposal"]["enum"] == [
            "capture", "void", "wait", "reauthorize",
        ]
        assert "nvext" not in body_json
        assert "29" not in body_json["messages"][0]["content"]
        await client.aclose()

    asyncio.run(body())


def test_report_temperature_is_about_0_2_unless_nim_env_overrides(monkeypatch):
    _enable("nim")
    monkeypatch.setenv("NIM_TEMPERATURE", "0.33")
    seen, client = _transport({
        "integrate.api.nvidia.com": [_openai("Fait pour dep-mayotte.", llm.nim_model())],
    })
    monkeypatch.setattr(llm, "_client", lambda: client)

    async def body():
        await record_evidence("dep-mayotte", met=True, facts={"port": "Mayotte"})
        result = await review("dep-mayotte", reader=None)
        assert seen[0]["body"]["temperature"] == 0.33
        assert "Mayotte" in result["report"]
        assert "Dep-Mayotte" not in result["report"]
        assert "dep-" not in result["report"].lower()
        assert result["proposal"] == "capture"

    asyncio.run(body())


def test_private_nim_id_is_the_default_and_a_404_is_counted(monkeypatch, caplog):
    assert llm.NIM_MODEL_DEFAULT.startswith("private/nvidia/nemotron-3.5-super-120b-a12b")
    render = (Path(__file__).resolve().parents[2] / "render.yaml").read_text(encoding="utf-8")
    assert "private/nvidia/nemotron-3.5-super-120b-a12b" in render
    assert "returns 404" in render
    llm.reset_nim_404_fallbacks()
    _enable("nim")
    seen, client = _transport({
        "integrate.api.nvidia.com": [
            httpx.Response(404, json={"error": {"message": "model not found"}}),
            _openai("secours", llm.NIM_FALLBACK_MODEL_DEFAULT),
        ],
    })

    async def body():
        with caplog.at_level("WARNING"):
            result = await llm.ask_text("preuve", client=client)
        assert result.text == "secours"
        assert result.provider == "nim_fallback"
        assert result.model == llm.NIM_FALLBACK_MODEL_DEFAULT
        assert seen[0]["model"] == llm.NIM_MODEL_DEFAULT
        assert "http_404" in result.reason
        assert llm.NIM_MODEL_DEFAULT in result.reason
        assert "Bearer" not in result.reason
        assert llm.nim_404_fallback_count() == 1
        assert "returned 404" in caplog.text
        assert "sending model" in caplog.text or llm.NIM_MODEL_DEFAULT in caplog.text
        await client.aclose()

    asyncio.run(body())


def test_rejected_nim_model_env_sends_the_private_super(monkeypatch, caplog):
    """Render NIM_MODEL overrides the default. Known 404 ids and lightning are not sent."""
    assert llm.nim_model_reason() == ""
    monkeypatch.setenv("NIM_MODEL", "nvidia/nemotron-3.5-super-vl-120b-a12b")
    assert llm.nim_model() == llm.NIM_MODEL_DEFAULT
    assert "NIM_MODEL" in llm.nim_model_reason()
    assert "404" in llm.nim_model_reason()
    assert "nvapi" not in llm.nim_model_reason()
    monkeypatch.setenv("NIM_MODEL", "nvidia/nemotron-3.5-super-120b-a12b")
    assert llm.nim_model() == llm.NIM_MODEL_DEFAULT
    assert "private/" in llm.nim_model_reason()
    monkeypatch.setenv("NIM_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")
    assert llm.nim_model() == llm.NIM_MODEL_DEFAULT
    assert "lightning" in llm.nim_model_reason()
    monkeypatch.setenv("NIM_MODEL", "nvidia/benchmark-model")
    assert llm.nim_model() == "nvidia/benchmark-model"
    assert llm.nim_model_reason() == ""

    _enable("nim")
    monkeypatch.setenv("NIM_MODEL", "nvidia/nemotron-3.5-super-vl-120b-a12b")
    seen, client = _transport({
        "integrate.api.nvidia.com": [_openai("Rapport Super.", llm.NIM_MODEL_DEFAULT)],
    })

    async def body():
        with caplog.at_level("WARNING"):
            result = await llm.ask_text("preuve", client=client)
        assert seen[0]["model"] == llm.NIM_MODEL_DEFAULT
        assert result.provider == "nim"
        assert result.model == llm.NIM_MODEL_DEFAULT
        assert "NIM_MODEL" in result.reason
        assert "404" in result.reason
        assert "NIM_MODEL" in caplog.text
        assert "Bearer" not in caplog.text
        assert "nvapi" not in caplog.text
        await client.aclose()

    asyncio.run(body())


def test_nim_timeout_names_the_fallback_and_the_sent_id(caplog):
    _enable("nim")
    calls = []

    class Slow:
        async def post(self, url, headers=None, json=None, timeout=None):
            calls.append(json["model"])
            if len(calls) == 1:
                raise httpx.ReadTimeout("timed out")
            return httpx.Response(200, json={
                "model": json["model"],
                "choices": [{"message": {"content": "secours"}}],
            })

        async def aclose(self):
            return None

    async def body():
        with caplog.at_level("WARNING"):
            result = await llm.ask_text("preuve", client=Slow())
        assert calls[0] == llm.NIM_MODEL_DEFAULT
        assert calls[1] == llm.NIM_FALLBACK_MODEL_DEFAULT
        assert result.provider == "nim_fallback"
        assert result.model == llm.NIM_FALLBACK_MODEL_DEFAULT
        assert "timeout" in result.reason
        assert llm.NIM_MODEL_DEFAULT in result.reason
        assert "http_404" not in result.reason
        assert "Bearer" not in result.reason
        assert "timeout" in caplog.text
        assert llm.NIM_MODEL_DEFAULT in caplog.text

    asyncio.run(body())
