"""Veille Tavily + enrichissement science — faux Tavily + faux Nemotron."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

import escale_watch
import llm_budget
import voyage_journal as journal
from voyage_clock import parse_iso


NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
PORT = {
    "name": "Nouméa",
    "lat": -22.2758,
    "lon": 166.4483,
    "url": "https://www.portautonome.nc/",
}
SCI = {
    "name": "IRD Nouméa",
    "lat": -22.3,
    "lon": 166.44,
    "url": "https://www.ird.fr/noumea",
}
TAVILY_HIT = {
    "title": "Avis aux navigateurs — Motu Uta",
    "url": "https://www.portautonome.nc/avis",
    "content": "Travaux annoncés à la marina de Motu Uta.",
}
SUMMARY = "Travaux annoncés à la marina de Motu Uta"
ENRICH = "L'IRD Nouméa observe le climat du Pacifique Sud"


def _chat_ok(text, model="nvidia/Nemotron-3_5-Lightning"):
    return {
        "choices": [{"message": {"content": text}}],
        "model": model,
        "usage": {"prompt_tokens": 40, "completion_tokens": 20},
    }


def _handler(seen=None, search_body=None, summary=SUMMARY, extract_text=ENRICH):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if seen is not None:
            seen.append(url)
        if url.endswith("/search"):
            if search_body is not None:
                search_body.append(json.loads(request.read().decode()))
            return httpx.Response(200, json={"results": [TAVILY_HIT]})
        if url.endswith("/extract"):
            return httpx.Response(200, json={
                "results": [{"url": SCI["url"], "raw_content": extract_text}],
            })
        if "tokenfactory" in url:
            return httpx.Response(200, json=_chat_ok(summary))
        return httpx.Response(404, json={"detail": url})
    return handler


def _keys(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.setenv("NAVIGUIDE_TAVILY_WATCH", "1")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_watch_query_and_window():
    q = escale_watch.watch_query("Nouméa", when=NOW)
    assert q == "Nouméa avis aux navigateurs 2026-09-20"
    assert escale_watch.format_watch_question("travaux", "Nouméa", NOW) == (
        "Nouméa travaux port marina 2026-09-20"
    )
    assert escale_watch.format_watch_question("fermeture", "Nouméa", NOW) == (
        "Nouméa fermeture port 2026-09-20"
    )
    assert escale_watch.format_watch_question("inventée", "Nouméa", NOW) is None
    assert "noumea.nc" in escale_watch.official_domains("Nouméa")
    clock = {
        "t0": "2026-09-10T08:00:00Z",
        "marks": [
            {"name": "Nouméa", "iso": "2026-09-20T08:00:00Z", "lat": -22.27, "lon": 166.44},
            {"name": "Trop tôt", "iso": "2026-08-01T08:00:00Z"},
            {"name": "Trop tard", "iso": "2026-12-01T08:00:00Z"},
        ],
    }
    names = [s["name"] for s in escale_watch.stops_in_window(clock, NOW)]
    assert names == ["Nouméa"]
    late = NOW + timedelta(days=3)
    assert escale_watch.stops_in_window(clock, late) == []


def test_search_watch_does_not_cache_http_error(monkeypatch):
    _keys(monkeypatch)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"results": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await escale_watch.search_watch("Nouméa", client=client, now=NOW)

    first = asyncio.run(run())
    second = asyncio.run(run())
    for result in (first, second):
        assert result["reason"] == "http-error"
        assert result["status"] == 503
        assert result["results"] == []
        assert result["cached"] is False
    assert calls == 2


def test_one_watch_writes_news_with_url(monkeypatch):
    _keys(monkeypatch)
    journal.reset()
    seen, bodies = [], []

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(seen, bodies))) as client:
            return await escale_watch.watch_stop(PORT, NOW, client=client)

    entry = asyncio.run(run())
    assert entry["kind"] == "news"
    assert entry["name"] == "Nouméa"
    assert entry["url"] == TAVILY_HIT["url"]
    assert "Travaux" in entry["text"]
    assert "42" not in entry["text"]
    assert entry["id"] == "news:noumea"
    assert parse_iso(entry["expires"]) > NOW
    assert escale_watch.watch_done("Nouméa")
    logged = journal.latest(5, kinds=("news",))
    assert len(logged) == 1
    assert logged[0]["url"] == TAVILY_HIT["url"]
    assert any(u.endswith("/search") for u in seen)
    assert bodies[0]["topic"] == "news"
    assert bodies[0]["days"] == 7
    assert bodies[0]["max_results"] == 5
    assert llm_budget.tavily_usage()["credits"] == 1


def test_one_search_per_stop_even_across_days(monkeypatch):
    """15 oct. : une escale n'est cherchée qu'UNE fois — pas une fois par jour, pas toutes les 6 h."""
    _keys(monkeypatch)
    journal.reset()
    seen = []
    day1 = NOW
    day2 = NOW + timedelta(days=1)

    async def once(when):
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(seen))) as client:
            a = await escale_watch.watch_stop(PORT, when, client=client)
            b = await escale_watch.watch_stop(PORT, when, client=client)
            return a, b

    first, again = asyncio.run(once(day1))
    assert first and first["id"] == "news:noumea"
    assert again is None, "la seconde passe du même jour ne refait rien"
    searches = [u for u in seen if u.endswith("/search")]
    assert len(searches) == 1
    third, fourth = asyncio.run(once(day2))
    assert third is None and fourth is None, "le lendemain non plus : l'escale est faite"
    searches = [u for u in seen if u.endswith("/search")]
    assert len(searches) == 1
    assert llm_budget.tavily_usage()["credits"] == 1
    assert len(journal.latest(5, kinds=("news",))) == 1


def test_news_expires_after_arrival_not_after_search(monkeypatch):
    """Cherchée à J-10, la veille reste lisible jusqu'à J+2 après l'ARRIVÉE."""
    _keys(monkeypatch)
    journal.reset()
    arrival = NOW + timedelta(days=9)
    stop = {**PORT, "arrival": arrival}

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler([]))) as client:
            return await escale_watch.watch_stop(stop, NOW, client=client)

    entry = asyncio.run(run())
    assert entry
    assert parse_iso(entry["expires"]) > arrival + timedelta(days=2)
    assert not escale_watch.expired(entry, arrival + timedelta(days=1))
    assert escale_watch.expired(entry, arrival + timedelta(days=4))
    bag = escale_watch.attach_cached_news({"news": []}, NOW + timedelta(days=8))
    assert [n["id"] for n in bag["news"]] == ["news:noumea"], "rattachée au sac bien après trois jours"


def test_science_extract_attached_once(monkeypatch):
    _keys(monkeypatch)
    seen = []
    item = dict(SCI)

    async def once():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(seen, summary=ENRICH))) as client:
            return await escale_watch.enrich_entity(item, client=client)

    first = asyncio.run(once())
    assert first["text"]
    assert first["url"] == SCI["url"]
    assert item["enrich"]["text"] == first["text"]
    extracts = [u for u in seen if u.endswith("/extract")]
    assert len(extracts) == 1
    second = asyncio.run(once())
    assert second["text"] == first["text"]
    assert len([u for u in seen if u.endswith("/extract")]) == 1


def test_credit_budget_blocks_second_search(monkeypatch):
    _keys(monkeypatch)
    monkeypatch.setenv("NAVIGUIDE_TAVILY_DAILY_CREDITS", "1")
    seen = []
    other = {**PORT, "name": "Ajaccio"}

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(seen))) as client:
            a = await escale_watch.watch_stop(PORT, NOW, client=client)
            b = await escale_watch.watch_stop(other, NOW, client=client)
            return a, b

    a, b = asyncio.run(run())
    assert a and a["kind"] == "news"
    assert b is None
    assert len([u for u in seen if u.endswith("/search")]) == 1
    assert llm_budget.tavily_usage()["credits"] == 1
    assert llm_budget.allow_tavily() is False


def test_filter_numbers_drops_invented_figure():
    facts = {"results": [TAVILY_HIT]}
    cleaned, dropped = __import__("story_cascade", fromlist=["filter_numbers"]).filter_numbers(
        "Travaux pour 42 bateaux à Motu Uta.", facts,
    )
    assert dropped >= 1
    assert "42" not in cleaned


def test_ici_warm_hooks_daily_watch():
    src = Path(__file__).resolve().parents[1].joinpath("ici_warm.py").read_text()
    assert "escale_watch" in src
    assert "run_daily" in src
    assert "news" in Path(__file__).resolve().parents[1].joinpath("voyage_journal.py").read_text()


def test_question_outside_list_refused():
    left = {"travaux", "fermeture"}
    assert escale_watch.parse_second_question('{"question": "travaux"}', left) == "travaux"
    assert escale_watch.parse_second_question('{"question": "avis"}', left) is None
    assert escale_watch.parse_second_question('{"question": "inventée"}', left) is None
    assert escale_watch.parse_second_question("What is the weather in Noumea today?", left) is None
    assert escale_watch.parse_second_question('{"question": null}', left) is None


def test_flag_closed_zero_tavily_search(monkeypatch):
    _keys(monkeypatch)
    monkeypatch.setenv("NAVIGUIDE_TAVILY_WATCH", "0")
    seen = []

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(seen))) as client:
            return await escale_watch.watch_stop(PORT, NOW, client=client)

    assert asyncio.run(run()) is None
    assert [u for u in seen if u.endswith("/search")] == []
    assert not escale_watch.watch_done("Nouméa")


def test_default_watch_enabled(monkeypatch):
    """Défaut actif : sans variable d'env, watch_enabled() est True (PR #401)."""
    _keys(monkeypatch)
    # Ne pas forcer NAVIGUIDE_TAVILY_WATCH — on teste le défaut
    monkeypatch.delenv("NAVIGUIDE_TAVILY_WATCH", raising=False)
    assert escale_watch.watch_enabled() is True


def test_two_rounds_max_lightning_picks_from_list(monkeypatch):
    _keys(monkeypatch)
    journal.reset()
    seen, bodies = [], []

    def search_results(body):
        q = body.get("query") or ""
        if "avis aux navigateurs" in q:
            return []
        return [TAVILY_HIT]

    def handler(request: httpx.Request):
        url = str(request.url)
        seen.append(url)
        if url.endswith("/search"):
            body = json.loads(request.read().decode())
            bodies.append(body)
            return httpx.Response(200, json={"results": search_results(body)})
        if "tokenfactory" in url:
            payload = json.loads(request.read().decode())
            blob = json.dumps(payload, ensure_ascii=False)
            if "Lot TV1" in blob:
                return httpx.Response(200, json=_chat_ok('{"question": "travaux"}'))
            return httpx.Response(200, json=_chat_ok(SUMMARY))
        return httpx.Response(404, json={"detail": url})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await escale_watch.watch_stop(PORT, NOW, client=client)

    entry = asyncio.run(run())
    assert entry and "Travaux" in entry["text"]
    assert entry["url"] == TAVILY_HIT["url"]
    assert "42" not in entry["text"]
    assert entry.get("rounds") == 2
    assert entry.get("question") == "travaux"
    assert len(bodies) == 2
    allowed = {
        escale_watch.format_watch_question(q, "Nouméa", NOW)
        for q in escale_watch.WATCH_QUESTION_IDS
    }
    assert all(b["query"] in allowed for b in bodies)
    assert bodies[0]["query"] == "Nouméa avis aux navigateurs 2026-09-20"
    assert bodies[1]["query"] == "Nouméa travaux port marina 2026-09-20"


def test_no_third_round_even_if_lightning_asks(monkeypatch):
    _keys(monkeypatch)
    journal.reset()
    bodies = []

    def handler(request: httpx.Request):
        url = str(request.url)
        if url.endswith("/search"):
            body = json.loads(request.read().decode())
            bodies.append(body)
            return httpx.Response(200, json={"results": []})
        if "tokenfactory" in url:
            payload = json.loads(request.read().decode())
            blob = json.dumps(payload, ensure_ascii=False)
            if "Lot TV1" in blob:
                user = payload.get("messages") or []
                content = ""
                for msg in user:
                    if msg.get("role") == "user":
                        content = msg.get("content") or ""
                remaining = []
                try:
                    remaining = json.loads(content).get("remaining") or []
                except (TypeError, json.JSONDecodeError):
                    remaining = []
                pick = remaining[0] if remaining else "fermeture"
                return httpx.Response(200, json=_chat_ok(json.dumps({"question": pick})))
            return httpx.Response(200, json=_chat_ok(SUMMARY))
        return httpx.Response(404, json={"detail": url})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await escale_watch.watch_stop(PORT, NOW, client=client)

    assert asyncio.run(run()) is None
    assert len(bodies) == 2
    assert all("fermeture" not in (b.get("query") or "") for b in bodies)


def test_invented_question_never_sent_to_tavily(monkeypatch):
    _keys(monkeypatch)
    journal.reset()
    bodies = []

    def handler(request: httpx.Request):
        url = str(request.url)
        if url.endswith("/search"):
            body = json.loads(request.read().decode())
            bodies.append(body)
            return httpx.Response(200, json={"results": [TAVILY_HIT]})
        if "tokenfactory" in url:
            payload = json.loads(request.read().decode())
            blob = json.dumps(payload, ensure_ascii=False)
            if "Lot TV1" in blob:
                return httpx.Response(200, json=_chat_ok(
                    '{"question": "Nouméa weather forecast tomorrow"}'
                ))
            return httpx.Response(200, json=_chat_ok(SUMMARY))
        return httpx.Response(404, json={"detail": url})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await escale_watch.watch_stop(PORT, NOW, client=client)

    entry = asyncio.run(run())
    assert entry and entry["url"] == TAVILY_HIT["url"]
    assert len(bodies) == 1
    assert bodies[0]["query"] == "Nouméa avis aux navigateurs 2026-09-20"
    assert "weather" not in bodies[0]["query"]


def test_daily_search_cap_blocks_next_stop(monkeypatch):
    _keys(monkeypatch)
    monkeypatch.setenv("NAVIGUIDE_WATCH_DAILY_SEARCHES", "1")
    journal.reset()
    seen = []
    other = {**PORT, "name": "Ajaccio"}

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(seen))) as client:
            a = await escale_watch.watch_stop(PORT, NOW, client=client)
            b = await escale_watch.watch_stop(other, NOW, client=client)
            return a, b

    a, b = asyncio.run(run())
    assert a and a["kind"] == "news"
    assert b is None
    assert len([u for u in seen if u.endswith("/search")]) == 1


def test_watch_phrase_for_fiche_not_chat_when_in_film():
    phrase = "Travaux annoncés à la marina de Motu Uta"
    entry = escale_watch.news_entry(
        PORT, phrase, TAVILY_HIT["url"], NOW, question="travaux", rounds=1,
    )
    assert entry["text"] == phrase
    assert entry["url"] == TAVILY_HIT["url"]
    escale_watch.set_watch_in_film(False)
    kept = escale_watch.drop_news_if_in_film([entry, {"kind": "stop", "name": "Nouméa"}])
    assert [e["kind"] for e in kept] == ["news", "stop"]
    escale_watch.set_watch_in_film(True)
    dropped = escale_watch.drop_news_if_in_film([entry, {"kind": "stop", "name": "Nouméa"}])
    assert [e["kind"] for e in dropped] == ["stop"]


def test_status_records_last_port_not_the_query(monkeypatch):
    _keys(monkeypatch)
    journal.reset()

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler([]))) as client:
            return await escale_watch.watch_stop(PORT, NOW, client=client)

    entry = asyncio.run(run())
    assert entry and entry["name"] == "Nouméa"
    tv = llm_budget.status()["tavily"]
    assert tv["calls"] >= 1
    assert tv["lastPort"] == "Nouméa"
    assert isinstance(tv["lastAt"], str) and "T" in tv["lastAt"]
    assert "query" not in tv
    blob = json.dumps(tv)
    assert "avis aux navigateurs" not in blob
    assert "tvly-" not in blob


def test_run_daily_without_enrich_skips_pearls(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_TAVILY_WATCH", "0")
    called: list = []

    async def spy_enrich(*_a, **_k):
        called.append(1)
        return {"wrote": 0}

    monkeypatch.setattr(escale_watch, "run_daily_enrich", spy_enrich)

    async def run():
        return await escale_watch.run_daily(enrich=False)

    out = asyncio.run(run())
    assert called == []
    assert out["enrich"]["skipped"] is True
    assert out["enrich"]["reason"] == "watch-only"


def test_watch_enabled_by_default(monkeypatch):
    """Default is now 1 (watch enabled) — no env var means watch runs."""
    monkeypatch.delenv("NAVIGUIDE_TAVILY_WATCH", raising=False)
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("NEBIUS_API_KEY", "tf-test")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert escale_watch.watch_enabled() is True
