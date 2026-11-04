"""Cache de lecture des récits : (type, stableKey, lang), cascade, budget. Plus de pré-génération."""
import asyncio

import httpx
from fastapi.testclient import TestClient

import pearl_store
import story_cache
import story_cascade
from tests.test_voyage_journal import PUBLIC


def _llm(answer="Le bateau entre dans la ZEE espagnole ; ports d’entrée officiels : Bilbao, Santander."):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "tokenfactory" in url or "integrate.api.nvidia.com" in url or "openrouter.ai" in url or "api.anthropic.com" in url:
            calls.append(url)
            return httpx.Response(200, json={"choices": [{"message": {"content": answer}}]})
        return httpx.Response(404)
    return httpx.MockTransport(handler), calls


def test_key_only_for_position_independent_events():
    assert story_cache.story_key({"type": "zee-enter", "stableKey": "zee-enter:5693", "lang": "fr"}) == "zee-enter|zee-enter:5693|fr"
    assert story_cache.story_key({"event": "poe-ahead", "stableKey": "poe-ahead:5693:Bilbao", "lang": "en-GB"}) == "poe-ahead|poe-ahead:5693:Bilbao|en"
    assert story_cache.story_key({"type": "wind-gale", "stableKey": "wind-gale:x"}) is None, "a gale is written live"
    assert story_cache.story_key({"type": "zee-enter"}) is None, "no stable key, no cache"


def test_story_endpoint_reads_the_cache_then_writes_through_it(monkeypatch):
    monkeypatch.setattr(story_cascade, "nebius_key", lambda: "test")
    monkeypatch.setattr(story_cascade, "nvidia_key", lambda: "test")
    transport, calls = _llm()
    real = story_cascade.write_story

    async def patched(body, client=None):
        async with httpx.AsyncClient(transport=transport) as c:
            return await real(body, c)

    monkeypatch.setattr(story_cascade, "write_story", patched)
    import main
    monkeypatch.setattr(main, "write_story", patched)
    from main import app
    client = TestClient(app)
    body = {"event": "zee-enter", "type": "zee-enter", "stableKey": "zee-enter:5693", "lang": "fr", "payload": {"zee": {"name": "Spanish EEZ", "mrgid": 5693}}}
    r1 = client.post("/ici/story", json=body, headers=PUBLIC).json()
    assert r1["status"] == "ready" and r1["cached"] is False and len(calls) == 1
    assert r1["source"] == "nemotron-super-vl"
    assert any("tokenfactory.nebius.com" in u for u in calls)
    r2 = client.post("/ici/story", json={**body, "eventId": "other"}, headers=PUBLIC).json()
    assert r2["status"] == "ready" and r2["cached"] is True and r2["engine"].startswith("cache:")
    assert r2["source"] == "cache"
    assert r2["text"] == r1["text"]
    assert len(calls) == 1, "served from the store"
    assert story_cache.budget_used_today() == 1
    # A gale is never cached.
    gale = {"event": "wind-gale", "type": "wind-gale", "stableKey": "wind-gale:x", "lang": "fr", "payload": {}}
    client.post("/ici/story", json=gale, headers=PUBLIC)
    client.post("/ici/story", json=gale, headers=PUBLIC)
    # gale is not in the story store, but cascade_text caches the prompt.
    assert len(calls) == 2
    assert pearl_store.kv_count("story") == 1


def test_pregeneration_removed():
    assert not hasattr(story_cache, "pregenerate_official")
    assert not hasattr(story_cache, "_pregenerate_official")
    assert not hasattr(story_cache, "pregen_bodies")
    st = story_cache.status()
    assert st.get("skipped") == "on-demand"
    assert "status" not in st or st.get("status") != "running"


def test_story_through_cache_keeps_writer_source():
    async def writer(body, client=None):
        return {"status": "ready", "text": "Entrée dans la ZEE.", "engine": "nemotron-super-vl", "source": "nemotron-super-vl"}

    body = {"type": "zee-enter", "stableKey": "zee-enter:l2", "lang": "fr"}
    out = asyncio.run(story_cache.story_through_cache(body, writer=writer))
    assert out["source"] == "nemotron-super-vl" and out["cached"] is False
    hit = story_cache.get_cached(body)
    assert hit["source"] == "cache"
    assert "nemotron-super-vl" in hit["engine"]


def test_story_through_cache_fills_source_from_engine_when_missing():
    async def writer(body, client=None):
        return {"status": "ready", "text": "Sortie de ZEE.", "engine": "rules"}

    body = {"type": "zee-exit", "stableKey": "zee-exit:l2", "lang": "fr"}
    out = asyncio.run(story_cache.story_through_cache(body, writer=writer))
    assert out["source"] == "rules"


def test_translate_key_includes_lang():
    fr = "Entrée dans la ZEE 5677."
    assert story_cache.translate_key(fr, "en").startswith("en|")
    assert story_cache.translate_key(fr, "en") != story_cache.translate_key(fr, "fr")
    assert story_cache.story_key({"type": "zee-enter", "stableKey": "zee-enter:1", "lang": "fr"}) != \
        story_cache.story_key({"type": "zee-enter", "stableKey": "zee-enter:1", "lang": "en"})


def test_story_through_cache_translates_cached_fr(monkeypatch):
    calls = []

    async def writer(body, client=None):
        calls.append(body.get("lang"))
        return {
            "status": "ready",
            "text": "Entrée dans la ZEE 5677.",
            "engine": "nemotron-super-vl",
            "source": "nemotron-super-vl",
        }

    async def fake_tr(text, lang, client=None, **kw):
        assert "5677" in text
        assert lang == "en"
        return "Entry into EEZ 5677.", "nemotron-lightning"

    monkeypatch.setattr(story_cascade, "translate", fake_tr)
    fr = {"type": "zee-enter", "stableKey": "zee-enter:l6", "lang": "fr"}
    en = {**fr, "lang": "en"}
    first = asyncio.run(story_cache.story_through_cache(fr, writer=writer))
    assert first["text"] == "Entrée dans la ZEE 5677." and calls == ["fr"]
    out = asyncio.run(story_cache.story_through_cache(en, writer=writer))
    assert out["text"] == "Entry into EEZ 5677."
    assert out["source"] == "nemotron-lightning"
    assert out["translatedFrom"] == "fr"
    assert calls == ["fr"], "EN réutilise le FR en cache, pas un second Super"
    hit = story_cache.get_cached(en)
    assert hit["text"] == "Entry into EEZ 5677."
    again = asyncio.run(story_cache.story_through_cache(en, writer=writer))
    assert again["cached"] is True and again["source"] == "cache"


def test_pregenerate_route_gone():
    from main import app
    client = TestClient(app)
    r = client.post("/ici/story/pregenerate", headers=PUBLIC)
    assert r.status_code in (404, 405)
