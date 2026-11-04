"""Juge de vérité — faux Tavily + faux Ultra."""
import asyncio
import json
import time
from pathlib import Path

import httpx

import llm_budget
import pytest


@pytest.fixture(autouse=True)
def _judge_budget(monkeypatch):
    """Depuis le 28 sept. le tier judge est plafonné à 0 par défaut (juge coupé) : ces tests exercent le module
    avec un faux modèle, ils rouvrent le plafond et sortent de l'arrière-plan pour la durée du test."""
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE", "1000000")
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "all")
    yield
import pearl_store
import truth_judge
from story_cascade import filter_numbers


FICHE = {
    "name": "Fort-de-France",
    "nm": 2.0,
    "url": "https://douane.gouv.fr/mq",
    "claim": "Visa 90 jours",
}
EXTRACT_OK = (
    "Fort-de-France est le port d'entrée officiel de la Martinique. "
    "Les formalités se font à la douane."
)
VERDICT_UNSUPPORTED = json.dumps({
    "supported": ["Fort-de-France est un port d'entrée officiel"],
    "unsupported": ["Visa 90 jours"],
    "stale_hint": "La mention du visa n'apparaît plus sur la page.",
}, ensure_ascii=False)


def _chat_ok(text, model="nvidia/Nemotron-3-Ultra-550b-a55b"):
    return {
        "choices": [{"message": {"content": text}}],
        "model": model,
        "usage": {"prompt_tokens": 80, "completion_tokens": 40},
    }


def _handler(ultra_text=VERDICT_UNSUPPORTED, extract_text=EXTRACT_OK, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if seen is not None:
            seen.append(url)
        if url.endswith("/extract"):
            return httpx.Response(200, json={
                "results": [{"url": FICHE["url"], "raw_content": extract_text}],
            })
        if url.endswith("/search"):
            return httpx.Response(200, json={"results": []})
        if "tokenfactory" in url:
            return httpx.Response(200, json=_chat_ok(ultra_text))
        return httpx.Response(404, json={"detail": url})
    return handler


def test_unsupported_claim_is_listed(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler())) as client:
            return await truth_judge.judge(FICHE, EXTRACT_OK, client=client)

    out = asyncio.run(run())
    assert out["status"] == "verified"
    assert "Visa 90 jours" in out["unsupported"]
    assert out["stale_hint"]


def test_empty_extract_is_unverifiable():
    async def run():
        return await truth_judge.judge(FICHE, "   ")

    out = asyncio.run(run())
    assert out["status"] == "unverifiable"
    assert out["unsupported"] == []


def test_budget_cap_makes_no_network(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE", "10")
    llm_budget.record("judge", 10, 0)
    seen = []

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(seen=seen))) as client:
            a = await truth_judge.judge(FICHE, EXTRACT_OK, client=client)
            b = await truth_judge.review_poe(FICHE, {"mrgid": 33178}, FICHE["url"], client=client)
            return a, b

    a, b = asyncio.run(run())
    assert a["status"] == "unverifiable" and a.get("reason") == "budget"
    assert b["status"] == "unverifiable" and b.get("reason") == "budget"
    assert seen == []


def test_cache_seven_days(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    seen = []

    async def once():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(seen=seen))) as client:
            return await truth_judge.review_poe(
                FICHE, {"mrgid": 33178, "gold": True}, FICHE["url"], client=client,
            )

    first = asyncio.run(once())
    assert first["status"] == "verified"
    n_first = len(seen)
    assert n_first >= 2  # extract + ultra
    second = asyncio.run(once())
    assert second["status"] == "verified"
    assert second["unsupported"] == first["unsupported"]
    assert len(seen) == n_first

    key = truth_judge.cache_key({"mrgid": 33178}, FICHE["url"])
    conn = pearl_store._connect()
    conn.execute(
        "UPDATE kv SET ts = ? WHERE ns = ? AND key = ?",
        (time.time() - 8 * 86400, truth_judge.NS, key),
    )
    assert pearl_store.kv_get(truth_judge.NS, key, truth_judge.TTL_S) is None
    third = asyncio.run(once())
    assert third["status"] == "verified"
    assert len(seen) > n_first


def test_filter_numbers_on_stale_hint():
    hint = "La mention du visa n'apparaît plus. Il faudrait 42 jours."
    cleaned, dropped = filter_numbers(hint, FICHE)
    assert "42" not in cleaned
    assert dropped >= 1
    assert truth_judge._filter_hint(hint, {"fiche": FICHE, "extract": EXTRACT_OK}) is not None
    assert truth_judge._filter_hint("Il faudra 99 kn demain.", FICHE) is None


def test_maybe_attach_disabled_by_default_returns_dossier_untouched(monkeypatch):
    monkeypatch.delenv("NAVIGUIDE_TRUTH_JUDGE", raising=False)
    bag = {"zee": {"gold": True}, "poe": [{"name": "Fort-de-France", "url": "https://example.org/poe"}]}
    out = asyncio.run(truth_judge.maybe_attach(dict(bag), client=None))
    assert "truth" not in (out["poe"][0] or {}), "éteint par défaut (28 sept.) : aucun appel, rien d'attaché"


def test_maybe_attach_writes_truth_on_gold_poe(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_TRUTH_JUDGE", "1")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    bag = {
        "zee": {"name": "Martinique", "mrgid": 33178, "gold": True},
        "poe": [dict(FICHE)],
    }

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler())) as client:
            return await truth_judge.maybe_attach(bag, client=client)

    out = asyncio.run(run())
    truth = out["poe"][0]["truth"]
    assert truth["status"] == "verified"
    assert "Visa 90 jours" in truth["unsupported"]
    assert truth["checkedAt"]


def test_ici_engine_hooks_maybe_attach():
    src = Path(__file__).resolve().parents[1].joinpath("ici_engine.py").read_text()
    assert "maybe_attach" in src
    assert "truth_judge" in src
