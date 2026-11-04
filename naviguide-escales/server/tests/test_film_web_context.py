"""Écart n° 43 : Tavily visible dans le film rédigé (provenance, jamais de texte inventé)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import film_web_context
import official_store
import port_web_context
import tavily_client
from official_store import DiskBackend, OfficialStore, READY

T0 = "2026-05-15T08:00:00Z"
NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
RAW_TEXT = (
    "Le 15 mai, Berry-Mappemonde quitte La Rochelle, cap au sud-ouest. "
    "Arrivée à Ajaccio le 26 mai."
)


def _plan():
    return {
        "chapters": [{
            "id": "c0", "text": RAW_TEXT, "tA": T0, "tB": T0,
            "fromName": "La Rochelle", "toName": "Ajaccio (Corse)",
            "anchors": [{"charIdx": 0, "t": T0}, {"charIdx": 60, "t": T0}],
        }],
        "source": "rules", "chars": len(RAW_TEXT), "targetSeconds": 150, "hasWritten": False,
    }


def _payload():
    plan = _plan()
    return {
        "fr": plan, "default": plan,
        "variants": {"fr": {"150": plan, "180": plan, "0": plan}},
        "estimates": {"fr": {"150": {"chars": plan["chars"], "estimatedSeconds": 10}}},
    }


def _voy():
    return {
        "t0": T0, "clock": {"t0": T0, "vertices": [{"lat": 1, "lon": 2, "iso": T0}]},
        "marks": [], "points": [{"lat": 1, "lon": 2}],
    }


async def _cascade(system, user, **kw):
    import json
    import re
    if "real stops" in (system or ""):
        return '{"ok": true, "faults": []}', "nemotron-super"
    match = re.search(r"sentences=(\[.*\])", user or "", re.S)
    sents = json.loads(match.group(1)) if match else ["ok."]
    return " ".join(s.replace("quitte", "laisse", 1) for s in sents), "nemotron-super"


def _install(tmp_path, monkeypatch):
    store = OfficialStore(DiskBackend(tmp_path / "disk-tavily-film"), now=lambda: NOW)
    voy = _voy()
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    monkeypatch.setattr(official_store, "_stored_last_stop", lambda: "Ajaccio")
    monkeypatch.delenv("NAVIGUIDE_LLM_MODE", raising=False)
    monkeypatch.delenv("NAVIGUIDE_PORT_WEB", raising=False)
    store.put("film", _payload(), store.family_key("film", voy, NOW))
    return store


def _fake_search(calls):
    async def search(query, **kw):
        calls.append(query)
        return {"results": [
            {"title": "Ajaccio — Noonsite", "url": "https://www.noonsite.com/place/france/corsica/ajaccio/",
             "content": "Port Tino Rossi, formalités."},
            {"title": "", "url": "https://example.org/ajaccio-marina", "content": "Marina."},
            {"title": "pas une URL", "url": "javascript:alert(1)", "content": "x"},
        ]}
    return search


def test_compact_keeps_only_public_provenance():
    out = film_web_context.compact({
        "status": "ready", "port": "Ajaccio", "fetchedAt": "2026-09-26T12:00:00Z",
        "sources": [
            {"title": "A", "url": "https://www.noonsite.com/a", "snippet": "extrait"},
            {"title": "B", "url": "ftp://x"},
        ],
        "excerpts": ["extrait"],
    })
    assert out == {
        "basis": "tavily", "port": "Ajaccio", "fetchedAt": "2026-09-26T12:00:00Z",
        "sources": [{"title": "A", "url": "https://www.noonsite.com/a", "domain": "noonsite.com"}],
    }
    assert film_web_context.compact({"status": "unavailable", "sources": []}) is None
    assert film_web_context.public({"basis": "other", "port": "X", "sources": []}) is None


def test_compact_dedupes_urls_by_normalized_key():
    out = film_web_context.compact({
        "status": "ready",
        "port": "Ajaccio",
        "fetchedAt": "2026-09-26T12:00:00Z",
        "sources": [
            {"title": "A", "url": "https://WWW.Example.COM/foo/"},
            {"title": "B", "url": "https://example.com/foo"},
            {"title": "C", "url": "https://other.org/bar"},
        ],
    })
    assert out is not None
    assert len(out["sources"]) == 2
    assert {s["domain"] for s in out["sources"]} == {"example.com", "other.org"}


def test_url_normalization_keeps_query_and_normalizes_host_port():
    assert film_web_context._normalize_url_key("https://WWW.Example.COM:8443/foo/?a=1#part") == (
        "https://example.com:8443/foo?a=1"
    )
    assert film_web_context._normalize_url_key("https://example.com/foo?a=2") != (
        film_web_context._normalize_url_key("https://example.com/foo?a=1")
    )


def test_compact_rejects_empty_url_host():
    assert film_web_context.compact({
        "status": "ready",
        "port": "Ajaccio",
        "fetchedAt": "2026-09-26T12:00:00Z",
        "sources": [{"title": "x", "url": "https://", "domain": "x.org"}],
    }) is None


def test_written_click_calls_tavily_and_film_serves_sources(tmp_path, monkeypatch):
    _install(tmp_path, monkeypatch)
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    calls: list[str] = []
    monkeypatch.setattr(tavily_client, "search", _fake_search(calls))

    asyncio.run(official_store.write_film_on_click("fr", 150, cascade=_cascade, now=NOW))
    assert len(calls) == 1
    assert "Ajaccio" in calls[0]

    written = official_store.serve_film("fr", 150, style="written")
    assert written["status"] == READY and written["hasWritten"] is True
    ctx = written["webContext"]
    assert ctx["basis"] == "tavily"
    assert ctx["port"] == "Ajaccio"
    assert [s["domain"] for s in ctx["sources"]] == ["noonsite.com", "example.org"]
    assert written["webSources"][0]["url"].startswith("https://www.noonsite.com/")
    # Aucun extrait web recopié dans le texte du film.
    text = " ".join(ch["text"] for ch in written["chapters"])
    assert "Tino Rossi" not in text
    assert "snippet" not in str(ctx)

    raw = official_store.serve_film("fr", 150, style="raw")
    assert raw["webContext"]["port"] == "Ajaccio"

    # Second clic le même jour : cache Tavily, pas de 2e crédit.
    asyncio.run(official_store.write_film_on_click("fr", 150, cascade=_cascade, now=NOW))
    assert len(calls) == 1


def test_get_never_calls_tavily_and_no_key_shows_nothing(tmp_path, monkeypatch):
    _install(tmp_path, monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(tavily_client, "search", _fake_search(calls))
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    out = official_store.serve_film("fr", 150, style="written")
    assert calls == []
    assert "webContext" not in out

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    asyncio.run(official_store.write_film_on_click("fr", 150, cascade=_cascade, now=NOW))
    assert calls == []
    written = official_store.serve_film("fr", 150, style="written")
    assert written["hasWritten"] is True
    assert "webContext" not in written
    assert "webSources" not in written


def test_tavily_error_never_blocks_the_written_film(tmp_path, monkeypatch):
    _install(tmp_path, monkeypatch)
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    async def boom(*_a, **_k):
        raise RuntimeError("réseau")

    monkeypatch.setattr(tavily_client, "search", boom)
    asyncio.run(official_store.write_film_on_click("fr", 150, cascade=_cascade, now=NOW))
    written = official_store.serve_film("fr", 150, style="written")
    assert written["hasWritten"] is True
    assert "webContext" not in written


def test_port_web_cache_is_shared_with_chat(monkeypatch):
    """Même cache que le chat journal : la requête du film est celle de port_web_context."""
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    calls: list[str] = []
    monkeypatch.setattr(tavily_client, "search", _fake_search(calls))
    a = asyncio.run(film_web_context.fetch_for_port("Ajaccio", now=NOW))
    b = asyncio.run(port_web_context.fetch_port_web("Ajaccio", now=NOW))
    assert a and a["port"] == "Ajaccio"
    assert b["status"] == "ready"
    assert len(calls) == 1
    assert asyncio.run(film_web_context.fetch_for_port("", now=NOW)) is None
