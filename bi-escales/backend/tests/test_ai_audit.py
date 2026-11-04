"""AI audit matrix. HTTP is mocked. No provider is contacted and no key is printed."""
from __future__ import annotations

import asyncio
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import llm
from app.escales.captain import chat, review
from app.escales.milestones import record_evidence
from app.escales.pledges import reset_ledger
from app.routers.escales import router, set_paypal_client_factory

SUPER = "I'd like to sponsor 120 nautical miles near Ajaccio"
FRENCH = "Je voudrais parrainer 120 milles près d'Ajaccio"


def _enable_nim(monkeypatch) -> None:
    monkeypatch.setenv("ESCALES_LLM_ENABLED", "1")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")


def _openai(text: str, model: str, status: int = 200, retry_after: str = "") -> httpx.Response:
    headers = {"retry-after": retry_after} if retry_after else None
    return httpx.Response(
        status,
        headers=headers,
        json={
            "model": model,
            "choices": [{"message": {"role": "assistant", "content": text}}],
        },
    )


def _transport(script: dict[str, list[httpx.Response]]):
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        seen.append({
            "host": request.url.host,
            "model": body.get("model"),
            "body": body,
            "headers": dict(request.headers),
        })
        queue = script.get(request.url.host)
        if not queue:
            raise AssertionError(f"unexpected host {request.url.host}")
        return queue.pop(0)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return seen, client


def _french_only(reply: str) -> None:
    folded = reply.casefold()
    for word in ("stopover", "leg", "intent"):
        assert word not in folded, reply


def _english_only(reply: str) -> None:
    folded = reply.casefold()
    for word in ("escale", "milles", "parrain", "trésorier", "étape", "quelle"):
        assert word not in folded, reply


def test_1_english_sponsorship_names_the_computed_line(monkeypatch):
    async def fake_ask(*_args, **_kwargs):
        return llm.LlmResult("The sea is calm.", "nim", llm.NIM_MODEL_DEFAULT)

    monkeypatch.setattr(llm, "has_llm", lambda: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask)

    async def body():
        result = await chat(SUPER, lang="en")
        reply = result["reply"]
        _english_only(reply)
        assert "120 sponsored miles (120.00 EUR)" in reply
        assert "Ajaccio" in reply
        assert reply.casefold().count("treasurer decides") == 0
        assert "arrival at the stop" in reply
        assert "PayPal Vault" in reply
        source = result["model_source"]
        super_answered = source.get("provider") == "nim" and "super" in source.get("model", "")
        assert super_answered or source.get("fallback_reason")

    asyncio.run(body())


def test_2_french_sponsorship_stays_in_french():
    async def body():
        result = await chat(FRENCH, lang="fr")
        reply = result["reply"]
        _french_only(reply)
        assert "120 milles parrainés (120,00 €)" in reply

    asyncio.run(body())


def test_3_english_cabin_between_la_rochelle_and_ajaccio():
    async def body():
        result = await chat("How much is a cabin from La Rochelle to Ajaccio?", lang="en")
        reply = result["reply"]
        assert "1 cabin leg (80.00 EUR)" in reply
        assert "2026-11-12 -> 2026-11-29" in reply
        dates = [s for s in re.split(r"(?<=[.!?])\s+", reply) if re.search(r"\d{4}-\d{2}-\d{2}", s)]
        assert dates == ["Schedule dates: 2026-11-12 -> 2026-11-29."]
        assert not reply.startswith("2026-")
        assert "2025" not in reply
        assert result["suggested_pledge"]["amount_eur"] == "80.00"

    asyncio.run(body())


def test_4_french_cabin_between_la_rochelle_and_ajaccio():
    async def body():
        result = await chat("Combien coûte une cabine de La Rochelle à Ajaccio ?", lang="fr")
        reply = result["reply"]
        assert "1 cabine (80,00 €)" in reply
        assert "escale" in reply.casefold()
        assert "stopover" not in reply.casefold()

    asyncio.run(body())


def test_5_app_language_english_wins_over_french_text():
    async def body():
        result = await chat(FRENCH, lang="en")
        reply = result["reply"]
        _english_only(reply)
        assert "120 sponsored miles (120.00 EUR)" in reply

    asyncio.run(body())


def test_6_app_language_french_wins_over_english_text():
    async def body():
        result = await chat(SUPER, lang="fr")
        reply = result["reply"]
        _french_only(reply)
        assert "120 milles parrainés (120,00 €)" in reply

    asyncio.run(body())


def test_7_english_cabin_without_a_stop_asks_which_stopover():
    async def body():
        result = await chat("How much is a cabin?", lang="en")
        reply = result["reply"]
        assert "Which stopover?" in reply
        assert "80" not in reply
        assert result["suggested_pledge"] is None

    asyncio.run(body())


def test_8_french_cabin_without_a_stop_asks_which_escale():
    async def body():
        result = await chat("Combien coûte une cabine ?", lang="fr")
        reply = result["reply"]
        assert "Quelle escale" in reply
        assert "80" not in reply
        assert "stopover" not in reply.casefold()

    asyncio.run(body())


def test_f6_sponsor_miles_without_a_stopover_asks_which_stopover():
    async def body():
        result = await chat("Sponsor 10 miles", lang="en")
        reply = result["reply"]
        assert "Which stopover?" in reply
        assert result["suggested_pledge"] is None
        assert "10.00" not in reply

    asyncio.run(body())


def test_9_english_capture_rule_does_not_move_money():
    async def body():
        result = await chat("When is my mile pledge money captured?", lang="en")
        reply = result["reply"]
        assert "arrival at the stop" in reply
        assert "Common fund pledges are captured at once" in reply
        assert result["suggested_pledge"] is None
        assert "AUTHORIZE" not in reply

    asyncio.run(body())


def test_10_french_capture_rule_does_not_move_money():
    async def body():
        result = await chat("Quand l'argent des milles est-il capturé ?", lang="fr")
        reply = result["reply"]
        assert "à l'arrivée du bateau à l'escale" in reply
        assert result["suggested_pledge"] is None
        assert "stopover" not in reply.casefold()

    asyncio.run(body())


def test_11_departure_question_has_no_past_year():
    async def body():
        result = await chat("When does the boat leave?", lang="en")
        reply = result["reply"]
        for year in ("2019", "2020", "2021", "2022", "2023", "2024", "2025"):
            assert year not in reply
        assert result["suggested_pledge"] is None

    asyncio.run(body())


def test_12_huge_mileage_keeps_only_the_computed_price(monkeypatch):
    async def fake_ask(*_args, **_kwargs):
        return llm.LlmResult("The secret price is 7 EUR and also 999999.", "nim", llm.NIM_MODEL_DEFAULT)

    monkeypatch.setattr(llm, "has_llm", lambda: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask)

    async def body():
        result = await chat("Sponsor 1000000 miles near Ajaccio", lang="en")
        reply = result["reply"]
        amount = result["suggested_pledge"]["amount_eur"]
        assert amount != "1000000.00"
        assert Decimal(amount) < Decimal("1000000")
        assert Decimal(amount) >= Decimal("1")
        assert "1000000" not in reply
        assert "999999" not in reply
        assert "7 EUR" not in reply
        dates = [s for s in re.split(r"(?<=[.!?])\s+", reply) if re.search(r"\d{4}-\d{2}-\d{2}", s)]
        assert len(dates) == 1
        assert not reply.startswith("2026-")

    asyncio.run(body())


def test_13_advisory_json_matches_the_schema_and_invalid_json_keeps_the_code(monkeypatch):
    calls = {"n": 0}

    async def fake_json(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return llm.LlmJson(
                {"proposal": "capture", "reason": "The evidence is met."},
                "nim_fallback",
                llm.NIM_FALLBACK_MODEL_DEFAULT,
                '{"proposal":"capture","reason":"The evidence is met."}',
            )
        raise RuntimeError("advisory schema")

    async def fake_text(*_args, **_kwargs):
        return llm.LlmResult("The evidence is recorded.", "nim", llm.NIM_MODEL_DEFAULT)

    monkeypatch.setattr(llm, "has_llm", lambda: True)
    monkeypatch.setattr(llm, "ask_text", fake_text)
    monkeypatch.setattr(llm, "ask_json", fake_json)
    reset_ledger()

    async def body():
        await record_evidence("lorient", met=True, facts={"port": "Lorient"})
        captured = await review("lorient", reader=None)
        assert captured["proposal"] == "capture"
        advisory = captured["llm_proposal"]
        assert advisory["proposal"] == "capture"
        assert advisory["proposal"] in {"capture", "void", "wait", "reauthorize"}
        assert isinstance(advisory["reason"], str) and advisory["reason"]
        assert llm.advisory_matches_schema({
            "proposal": advisory["raw_proposal"],
            "reason": advisory["raw_reason"],
        })

        await record_evidence("dakar", met=False, facts={"port": "Dakar"})
        voided = await review("dakar", reader=None)
        assert voided["proposal"] == "void"
        assert voided["llm_proposal"] is None

    asyncio.run(body())
    reset_ledger()


def test_14_super_429_honours_retry_after_and_answers(monkeypatch):
    _enable_nim(monkeypatch)
    pauses = []
    clock = {"t": 0.0}

    def mono():
        return clock["t"]

    async def fake_sleep(seconds):
        pauses.append(seconds)
        clock["t"] += seconds

    monkeypatch.setattr(llm.time, "monotonic", mono)
    monkeypatch.setattr(llm.asyncio, "sleep", fake_sleep)
    monkeypatch.setenv("ESCALES_NIM_GAP_S", "1.25")
    llm.reset_nim_pace()
    llm.reset_hop_blocks()
    seen, client = _transport({
        "integrate.api.nvidia.com": [
            _openai("", llm.NIM_MODEL_DEFAULT, status=429, retry_after="9"),
            _openai("Super held.", llm.NIM_MODEL_DEFAULT),
        ],
    })

    async def body():
        result = await llm.ask_text("preuve", client=client)
        assert result.provider == "nim"
        assert result.model == llm.NIM_MODEL_DEFAULT
        assert result.text == "Super held."
        assert pauses == [3.0]
        assert [item["model"] for item in seen] == [llm.NIM_MODEL_DEFAULT, llm.NIM_MODEL_DEFAULT]
        assert "nvext" not in seen[0]["body"]
        assert "reasoning_effort" not in seen[0]["body"]
        await client.aclose()

    asyncio.run(body())


def test_15_super_404_sets_fallback_reason_and_skips_for_ten_minutes(monkeypatch, caplog):
    _enable_nim(monkeypatch)
    llm.reset_hop_blocks()
    llm.reset_nim_404_fallbacks()
    seen, client = _transport({
        "integrate.api.nvidia.com": [
            httpx.Response(404, json={"error": {"message": "nope"}}),
            _openai("Lightning held.", llm.NIM_FALLBACK_MODEL_DEFAULT),
            _openai("Lightning again.", llm.NIM_FALLBACK_MODEL_DEFAULT),
        ],
    })

    async def body():
        with caplog.at_level("WARNING"):
            first = await llm.ask_text("preuve", client=client)
        assert first.provider == "nim_fallback"
        assert first.model == llm.NIM_FALLBACK_MODEL_DEFAULT
        assert first.text == "Lightning held."
        assert first.fallback_reason == {"nim": "HTTP 404"}
        assert llm.hop_block_remaining("nim") >= 500
        assert "model unavailable for this key" in caplog.text
        assert "test-nvidia-key" not in caplog.text
        second = await llm.ask_text("encore", client=client)
        assert second.text == "Lightning again."
        assert second.fallback_reason.get("nim") == "HTTP 404"
        assert [item["model"] for item in seen] == [
            llm.NIM_MODEL_DEFAULT,
            llm.NIM_FALLBACK_MODEL_DEFAULT,
            llm.NIM_FALLBACK_MODEL_DEFAULT,
        ]
        await client.aclose()

    asyncio.run(body())


def test_openrouter_defaults_to_the_free_model_and_skips_402(monkeypatch):
    monkeypatch.setenv("ESCALES_LLM_ENABLED", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    for name in (
        "NVIDIA_API_KEY", "ANTHROPIC_API_KEY", "NEBIUS_API_KEY",
        "ESCALES_LLM_NEBIUS_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    assert llm.openrouter_model() == "openrouter/free"
    assert "gpt-4o" not in llm.OPENROUTER_DEFAULT_MODEL
    seen, client = _transport({
        "openrouter.ai": [
            httpx.Response(402, json={"error": {"message": "payment required"}}),
        ],
        "api.anthropic.com": [],
    })

    async def body():
        with pytest.raises(RuntimeError):
            await llm.ask_text("preuve", client=client, guided_json=llm.ADVISORY_PROPOSAL_SCHEMA)
        assert seen[0]["model"] == "openrouter/free"
        assert seen[0]["headers"]["http-referer"]
        assert seen[0]["headers"]["x-title"] == "BI Escales"
        assert seen[0]["body"]["response_format"]["type"] == "json_schema"
        assert "test-openrouter-key" not in json.dumps(seen[0]["body"])
        await client.aclose()

    asyncio.run(body())


def test_router_uses_app_language_only(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin-key")
    monkeypatch.delenv("ESCALES_LLM_ENABLED", raising=False)
    reset_ledger()
    set_paypal_client_factory(lambda: object())
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        english = client.post(
            "/api/escales/captain/chat",
            json={"message": FRENCH, "lang": "en"},
        )
        assert english.status_code == 200, english.text
        assert "120 sponsored miles (120.00 EUR)" in english.json()["reply"]
        default_en = client.post(
            "/api/escales/captain/chat",
            json={"message": FRENCH},
            headers={"accept-language": "fr-FR,fr;q=0.9"},
        )
        assert "120 sponsored miles (120.00 EUR)" in default_en.json()["reply"]
        french = client.post(
            "/api/escales/captain/chat",
            json={"message": "I'd like to sponsor 120 miles near Ajaccio", "lang": "fr"},
        )
        assert "milles parrain" in french.json()["reply"]
        unknown = client.post(
            "/api/escales/captain/chat",
            json={"message": FRENCH, "lang": "de"},
        )
        assert "120 sponsored miles (120.00 EUR)" in unknown.json()["reply"]
    set_paypal_client_factory(None)


def test_startup_log_names_model_ids_only(caplog):
    with caplog.at_level("INFO"):
        llm.log_effective_nim_models()
    assert llm.NIM_MODEL_DEFAULT in caplog.text
    assert llm.NIM_FALLBACK_MODEL_DEFAULT in caplog.text
    assert "nvapi" not in caplog.text
    assert "sk-" not in caplog.text


def test_inverted_date_sentence_is_dropped():
    from app.escales.captain import _drop_inverted_ranges

    dropped = _drop_inverted_ranges("The cabin runs from 2026-12-02 to 2026-11-29. The sea is calm.")
    assert "2026-12-02" not in dropped
    assert "2026-11-29" not in dropped
    assert "The sea is calm" in dropped


def test_admin_llm_cascade_probe_returns_metadata_only(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin-key")
    reset_ledger()
    set_paypal_client_factory(lambda: object())

    async def fake_probe():
        return {
            "chat": {
                "provider": "nim",
                "model": llm.NIM_MODEL_DEFAULT,
                "fallback_reason": {"nim_fallback": "HTTP 404"},
            },
            "report": {"provider": "nim_fallback", "model": llm.NIM_FALLBACK_MODEL_DEFAULT},
            "ask_json": {
                "provider": "nim_fallback",
                "model": llm.NIM_FALLBACK_MODEL_DEFAULT,
                "fallback_reason": {"nim": "HTTP 404"},
            },
        }

    monkeypatch.setattr(llm, "probe_cascade", fake_probe)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        denied = client.get("/api/escales/admin/llm-cascade-probe")
        assert denied.status_code == 401
        ok = client.get(
            "/api/escales/admin/llm-cascade-probe",
            headers={"x-admin-key": "test-admin-key"},
        )
        assert ok.status_code == 200, ok.text
        payload = ok.json()
        assert set(payload) == {"chat", "report", "ask_json"}
        blob = json.dumps(payload)
        assert "test-admin-key" not in blob
        assert "nvapi" not in blob
        assert payload["chat"]["provider"] == "nim"
        assert payload["chat"]["fallback_reason"]["nim_fallback"] == "HTTP 404"
        assert "reply" not in blob
        assert "content" not in blob
    set_paypal_client_factory(None)
