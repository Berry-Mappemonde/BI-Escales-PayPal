"""Fiche d'escale : listes de faits OSM + BI, paragraphe par la cascade, cache 7 j."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import escale_api
import ici_engine
import pearl_store
import story_cascade
from tests.test_ici_engine import _handler  # mock BI + MarineRegions


def _osm_elements():
    return [
        {"type": "node", "id": 1, "lat": 46.1500, "lon": -1.1700, "tags": {"amenity": "fuel", "name": "Station du port", "fuel:diesel": "yes", "opening_hours": "Mo-Su 08:00-20:00"}},
        {"type": "node", "id": 2, "lat": 46.1520, "lon": -1.1650, "tags": {"amenity": "drinking_water"}},
        {"type": "way", "id": 3, "center": {"lat": 46.1600, "lon": -1.1500}, "tags": {"shop": "supermarket", "name": "Carrefour Market", "website": "https://carrefour.fr"}},
        {"type": "node", "id": 4, "lat": 46.1480, "lon": -1.1720, "tags": {"shop": "chandlery", "name": "Accastillage Diffusion", "phone": "+33 5 46 00 00 00"}},
        {"type": "way", "id": 5, "center": {"lat": 46.1450, "lon": -1.1800}, "tags": {"waterway": "boatyard", "name": "Chantier des Minimes"}},
        {"type": "node", "id": 6, "lat": 46.1580, "lon": -1.1530, "tags": {"tourism": "museum", "name": "Musée Maritime"}},
        {"type": "node", "id": 7, "lat": 46.1585, "lon": -1.1535, "tags": {"tourism": "attraction"}},  # unnamed: dropped
        {"type": "node", "id": 8, "lat": 46.1590, "lon": -1.1540, "tags": {"amenity": "pharmacy", "name": "Pharmacie du Port"}},
    ]


def _transport(calls=None, osm_fail=False):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if calls is not None:
            calls.append(url)
        if "overpass" in url:
            if osm_fail:
                return httpx.Response(503, text="busy")
            return httpx.Response(200, json={"elements": _osm_elements()})
        if "tokenfactory" in url or "integrate.api.nvidia.com" in url or "openrouter.ai" in url or "api.anthropic.com" in url:
            return httpx.Response(200, json={"choices": [{"message": {"content": "La Rochelle offre le Port des Minimes et une capitainerie. Carburant à la Station du port, courses au Carrefour Market. Port d’entrée officiel : La Rochelle - La Pallice."}}]})
        return _handler(request)
    return httpx.MockTransport(handler)


def test_classify_osm_groups_names_and_drops_unnamed_shops():
    out = escale_api.classify_osm(_osm_elements(), 46.15, -1.16)
    assert out["services"]["fuel"][0]["name"] == "Station du port"
    assert out["services"]["fuel"][0]["fuel"] == ["diesel"]
    assert out["services"]["water"][0]["name"] == "drinking water"  # a tap needs no name
    assert out["supplies"]["supermarkets"][0]["url"] == "https://carrefour.fr"
    assert out["maintenance"]["chandlery"][0]["phone"].startswith("+33")
    assert out["maintenance"]["boatyards"][0]["name"] == "Chantier des Minimes"
    assert [i["name"] for i in out["tourism"]["museums"]] == ["Musée Maritime"]
    assert "sights" not in out["tourism"], "unnamed attraction dropped"
    assert out["health"]["pharmacies"][0]["nm"] < 1


def test_build_escale_merges_bag_and_osm_and_writes_a_paragraph(monkeypatch):
    ici_engine.reset_caches()
    monkeypatch.setenv("NEBIUS_API_KEY", "test")
    monkeypatch.setenv("NVIDIA_API_KEY", "test")
    monkeypatch.setattr(story_cascade, "nebius_key", lambda: "test")
    monkeypatch.setattr(story_cascade, "nvidia_key", lambda: "test")
    calls = []

    async def run():
        async with httpx.AsyncClient(transport=_transport(calls)) as c:
            return await escale_api.build_escale("La Rochelle", 46.15, -1.16, "fr", client=c)

    fiche = asyncio.run(run())
    s = fiche["sections"]
    assert list(s.keys()) == [k for k in escale_api.SECTION_ORDER if k in s], "sections in reading order"
    assert "services" in s and "supplies" in s and "maintenance" in s and "tourism" in s
    assert s["formalities"]["zee"]["mrgid"] == 5677
    assert fiche["paragraph"]["status"] == "ready"
    assert "Minimes" in fiche["paragraph"]["text"]
    assert fiche["paragraph"]["source"] == "nemotron-lightning"
    assert fiche["sources"]["osm"] == "osm-overpass"
    assert any("overpass" in u for u in calls)


def test_without_llm_the_lists_stand_alone(monkeypatch):
    ici_engine.reset_caches()
    monkeypatch.setattr(story_cascade, "nebius_key", lambda: "")
    monkeypatch.setattr(story_cascade, "nvidia_key", lambda: "")
    monkeypatch.setattr(story_cascade, "openrouter_key", lambda: "")
    monkeypatch.setattr(story_cascade, "anthropic_key", lambda: "")

    async def run():
        async with httpx.AsyncClient(transport=_transport(osm_fail=True)) as c:
            return await escale_api.build_escale("La Rochelle", 46.15, -1.16, "fr", client=c)

    fiche = asyncio.run(run())
    assert fiche["paragraph"]["status"] == "failed"
    assert fiche["paragraph"]["text"] is None
    assert "services" not in fiche["sections"], "Overpass down: no invented services"
    assert fiche["sources"]["osm"].startswith("overpass_unavailable")
    assert "formalities" in fiche["sections"], "BI layers still there"


def test_endpoint_caches_seven_days(monkeypatch):
    ici_engine.reset_caches()
    calls = []
    transport = _transport(calls)
    real = escale_api.build_escale

    async def patched(name, lat, lon, lang="fr", client=None, **kw):
        async with httpx.AsyncClient(transport=transport) as c:
            return await real(name, lat, lon, lang, client=c, **kw)

    monkeypatch.setattr(escale_api, "build_escale", patched)
    from main import app
    client = TestClient(app)
    r = client.get("/escale?name=La%20Rochelle&lat=46.15&lon=-1.16&lang=fr")
    assert r.status_code == 200
    body = r.json()
    assert body["cached"] is False and body["sections"]
    n = len(calls)
    r2 = client.get("/escale?name=La%20Rochelle&lat=46.15&lon=-1.16&lang=fr")
    assert r2.json()["cached"] is True
    assert len(calls) == n, "served from the store"
    assert pearl_store.kv_count("escale") == 1
    assert client.get("/escale?name=x&lat=95&lon=0").status_code == 400


def test_endpoint_rebuilds_when_cached_paragraph_is_prompt(monkeypatch):
    """Un paragraphe-prompt en cache 7 j ne doit plus être servi."""
    key = escale_api.escale_key("La Rochelle", 46.15, -1.16, "en")
    pearl_store.kv_put("escale", key, {
        "name": "La Rochelle", "lat": 46.15, "lon": -1.16, "lang": "en",
        "sections": {"mooring": {"marinas": [{"name": "Minimes"}]}},
        "paragraph": {
            "status": "ready",
            "text": "Request: Present a stop/escales to a sailing crew arriving at La Rochelle.",
            "source": "rules",
        },
        "sources": {},
    })
    calls = []
    rebuilt = {
        "name": "La Rochelle", "lat": 46.15, "lon": -1.16, "lang": "en",
        "sections": {"mooring": {"marinas": [{"name": "Minimes"}]}},
        "paragraph": {
            "status": "ready",
            "text": "La Rochelle has the Minimes marina.",
            "source": "nemotron-lightning",
        },
        "sources": {},
    }

    async def patched(*_a, **_k):
        calls.append(1)
        return rebuilt

    monkeypatch.setattr(escale_api, "build_escale", patched)
    from main import app
    client = TestClient(app)
    body = client.get("/escale?name=La%20Rochelle&lat=46.15&lon=-1.16&lang=en").json()
    assert calls == [1]
    assert body["cached"] is False
    assert body["paragraph"]["text"] == "La Rochelle has the Minimes marina."
    assert "Request:" not in (body["paragraph"]["text"] or "")


def test_endpoint_rebuilds_when_cached_paragraph_is_nim(monkeypatch):
    """A NIM / tokenfactory-empty harbour paragraph must not stay 7 days."""
    key = escale_api.escale_key("Papeete", -17.54, -149.57, "en")
    assert key.endswith("|tf3")
    pearl_store.kv_put("escale", key, {
        "name": "Papeete", "lat": -17.54, "lon": -149.57, "lang": "en",
        "sections": {"mooring": {"marinas": [{"name": "Marina Taina"}]}},
        "paragraph": {
            "status": "ready",
            "text": "Papeete has a marina.",
            "source": "nvidia-nim",
        },
        "sources": {},
    })
    calls = []
    rebuilt = {
        "name": "Papeete", "lat": -17.54, "lon": -149.57, "lang": "en",
        "sections": {"mooring": {"marinas": [{"name": "Marina Taina"}]}},
        "paragraph": {
            "status": "ready",
            "text": "Papeete has the Marina Taina.",
            "source": "nemotron-lightning",
        },
        "sources": {},
    }

    async def patched(*_a, **_k):
        calls.append(1)
        return rebuilt

    monkeypatch.setattr(escale_api, "build_escale", patched)
    from main import app
    client = TestClient(app)
    body = client.get("/escale?name=Papeete&lat=-17.54&lon=-149.57&lang=en").json()
    assert calls == [1]
    assert body["cached"] is False
    assert body["paragraph"]["source"] == "nemotron-lightning"
    assert body["paragraph"]["text"] == "Papeete has the Marina Taina."
    assert escale_api.nim_paragraph({"paragraph": {"source": "nvidia-nim"}}) is True
    assert escale_api.nim_paragraph({"paragraph": {"source": "nemotron-lightning"}}) is False


def test_endpoint_strips_leaked_enrich_from_cache():
    """Un enrich science-prompt ne doit pas sortir sur la fiche."""
    key = escale_api.escale_key("La Rochelle", 46.15, -1.16, "en")
    pearl_store.kv_put("escale", key, {
        "name": "La Rochelle", "lat": 46.15, "lon": -1.16, "lang": "en",
        "sections": {
            "around": {"science": [{
                "name": "REPHY",
                "nm": 9.4,
                "enrich": {
                    "text": "**Analyze User Input:** Entity: REPHY dataset",
                    "url": "https://example.com/rephy",
                },
            }]},
        },
        "paragraph": {"status": "ready", "text": "La Rochelle has a marina.", "source": "rules"},
        "sources": {},
    })
    from main import app
    client = TestClient(app)
    body = client.get("/escale?name=La%20Rochelle&lat=46.15&lon=-1.16&lang=en").json()
    blob = json.dumps(body)
    assert "Analyze User Input" not in blob
    assert body["cached"] is True
    assert body["sections"]["around"]["science"][0]["name"] == "REPHY"
    enrich = body["sections"]["around"]["science"][0].get("enrich") or {}
    assert "Analyze" not in (enrich.get("text") or "")


CAPTURE_LEAK = (
    "Input: A large JSON object containing marina lists.\n"
    "- Task: Present a scale stop to a sailing crew arriving at Pointe-à-Pitre.\n"
    "What's for the boat, what's for the crew, what to know for formalities."
)


def test_endpoint_leaked_capture_returns_rules_and_invalidates_key(monkeypatch):
    """Cache 7 j avec le texte de la capture → repli rules, clé droppée."""
    key = escale_api.escale_key("Pointe-à-Pitre", 16.24, -61.53, "en")
    pearl_store.kv_put("escale", key, {
        "name": "Pointe-à-Pitre", "lat": 16.24, "lon": -61.53, "lang": "en",
        "sections": {"mooring": {"marinas": [{"name": "Bas-du-Fort"}]}},
        "paragraph": {"status": "ready", "text": CAPTURE_LEAK, "source": "nemotron-lightning"},
        "sources": {},
    })
    deleted = []
    real_delete = pearl_store.kv_delete

    def spy_delete(ns, k):
        deleted.append((ns, k))
        return real_delete(ns, k)

    monkeypatch.setattr(pearl_store, "kv_delete", spy_delete)
    rebuilt = {
        "name": "Pointe-à-Pitre", "lat": 16.24, "lon": -61.53, "lang": "en",
        "sections": {"mooring": {"marinas": [{"name": "Bas-du-Fort"}]}},
        "paragraph": {"status": "failed", "text": None, "engine": None, "source": "rules", "reason": "prompt leak"},
        "sources": {},
    }

    async def patched(*_a, **_k):
        return rebuilt

    monkeypatch.setattr(escale_api, "build_escale", patched)
    from main import app
    body = TestClient(app).get(
        "/escale?name=Pointe-%C3%A0-Pitre&lat=16.24&lon=-61.53&lang=en",
    ).json()
    blob = json.dumps(body)
    assert "Input:" not in blob
    assert "Task:" not in blob
    assert "JSON object" not in blob
    assert "What's for the boat" not in blob
    assert body["cached"] is False
    assert body["paragraph"]["source"] == "rules"
    assert body["paragraph"]["text"] is None
    assert ("escale", key) in deleted
    stored = ((pearl_store.kv_get("escale", key, escale_api.ESCALE_TTL_S) or {}).get("value") or {})
    assert "Input:" not in json.dumps(stored)
    assert (stored.get("paragraph") or {}).get("source") == "rules"


def test_endpoint_healthy_cache_is_served_unchanged():
    """Une fiche saine en cache ressort mot pour mot."""
    key = escale_api.escale_key("Pointe-à-Pitre", 16.24, -61.53, "en")
    text = "Pointe-à-Pitre has a marina at Bas-du-Fort and a harbour master's office."
    fiche = {
        "name": "Pointe-à-Pitre", "lat": 16.24, "lon": -61.53, "lang": "en",
        "sections": {"mooring": {"marinas": [{"name": "Bas-du-Fort"}]}},
        "paragraph": {"status": "ready", "text": text, "source": "nemotron-lightning"},
        "sources": {},
    }
    pearl_store.kv_put("escale", key, fiche)
    from main import app
    body = TestClient(app).get(
        "/escale?name=Pointe-%C3%A0-Pitre&lat=16.24&lon=-61.53&lang=en",
    ).json()
    assert body["cached"] is True
    assert body["paragraph"]["text"] == text
    assert body["paragraph"]["source"] == "nemotron-lightning"
    stored = ((pearl_store.kv_get("escale", key, escale_api.ESCALE_TTL_S) or {}).get("value") or {})
    assert stored["paragraph"]["text"] == text


def test_write_paragraph_uses_fast_tier_and_keeps_source(monkeypatch):
    seen = {}

    async def fake_cascade(system, user, client=None, **kw):
        seen.update(kw)
        return "La Rochelle a une marina et une capitainerie.", "nemotron-lightning"

    monkeypatch.setattr(escale_api, "cascade_text", fake_cascade)
    sections = {"mooring": {"marinas": [{"name": "Minimes", "nm": 0.2}]}}
    out = asyncio.run(escale_api.write_paragraph("La Rochelle", sections, "fr"))
    assert seen.get("tier") == "fast"
    assert out["status"] == "ready"
    assert out["source"] == "nemotron-lightning"
    assert out["engine"] == "nemotron-lightning"


def test_write_paragraph_en_translates_and_keeps_figures(monkeypatch):
    seen = []

    async def fake_cascade(system, user, client=None, **kw):
        seen.append(("cascade", kw.get("tier"), "français" in system or "Tu présentes" in system))
        return "La Rochelle a le Port des Minimes à 0,2 nm.", "nemotron-lightning"

    async def fake_tr(text, lang, client=None, **kw):
        seen.append(("translate", lang))
        assert "0,2" in text or "0.2" in text
        assert "Minimes" in text
        return "La Rochelle has the Port des Minimes at 0.2 nm.", "nemotron-lightning"

    monkeypatch.setattr(escale_api, "cascade_text", fake_cascade)
    monkeypatch.setattr(escale_api, "translate", fake_tr)
    sections = {"mooring": {"marinas": [{"name": "Minimes", "nm": 0.2}]}}
    out = asyncio.run(escale_api.write_paragraph("La Rochelle", sections, "en"))
    assert ("cascade", "fast", True) in seen
    assert ("translate", "en") in seen
    assert out["status"] == "ready"
    assert out["source"] == "nemotron-lightning"
    assert "Minimes" in out["text"]
    assert "0.2" in out["text"] or "0,2" in out["text"]
    assert "99" not in out["text"]


def _seed_fiche(name, lat, lon):
    key = escale_api.escale_key(name, lat, lon, "fr")
    pearl_store.kv_put("escale", key, {
        "name": name, "lat": lat, "lon": lon, "lang": "fr",
        "sections": {"mooring": {"marinas": [{"name": "Port"}]}},
        "paragraph": {"status": "ready", "text": "Le port accueille les voiliers.", "source": "rules"},
    })


def test_get_escale_schedules_one_watch_task(monkeypatch):
    """Escale dans la fenêtre : une tâche, pas une deuxième. Hors fenêtre : aucune."""
    from datetime import datetime, timedelta, timezone

    import voyage_store
    from voyage_clock import OFFICIAL_VOYAGE_ID

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    escale_api._INFLIGHT.clear()
    arrival = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%dT08:00:00Z")
    voyage_store.save_voyage({
        "voyageId": OFFICIAL_VOYAGE_ID,
        "points": [],
        "marks": [],
        "t0": "2026-01-01T00:00:00Z",
        "clock": {
            "t0": "2026-01-01T00:00:00Z",
            "marks": [{"name": "Nouméa", "iso": arrival, "lat": -22.27, "lon": 166.44}],
        },
    })
    _seed_fiche("Nouméa", -22.27, 166.44)
    _seed_fiche("Ajaccio", 41.92, 8.74)
    from main import app
    client = TestClient(app)
    monkeypatch.setenv("NAVIGUIDE_TAVILY_WATCH", "1")
    tasks: list = []
    real_create = asyncio.create_task

    def capture(coro, *args, **kwargs):
        code = getattr(coro, "cr_code", None)
        if code is not None and code.co_name == "watch_stop":
            tasks.append(code.co_name)
            coro.close()
            return real_create(asyncio.sleep(0))
        return real_create(coro, *args, **kwargs)

    monkeypatch.setattr(asyncio, "create_task", capture)
    try:
        url = "/escale?name=Noum%C3%A9a&lat=-22.27&lon=166.44&lang=fr"
        first = client.get(url)
        assert first.status_code == 200
        assert first.json()["cached"] is True
        assert tasks == ["watch_stop"]
        second = client.get(url)
        assert second.status_code == 200
        assert tasks == ["watch_stop"]
        other = client.get("/escale?name=Ajaccio&lat=41.92&lon=8.74&lang=fr")
        assert other.status_code == 200
        assert tasks == ["watch_stop"]
    finally:
        escale_api._INFLIGHT.clear()


def test_get_escale_no_watch_task_once_tavily_cap_reached(monkeypatch):
    """Plafond de crédits Tavily atteint : GET /escale ne lance aucune tâche de veille."""
    from datetime import datetime, timedelta, timezone

    import llm_budget
    import voyage_store
    from voyage_clock import OFFICIAL_VOYAGE_ID

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    escale_api._INFLIGHT.clear()
    arrival = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%dT08:00:00Z")
    voyage_store.save_voyage({
        "voyageId": OFFICIAL_VOYAGE_ID,
        "points": [],
        "marks": [],
        "t0": "2026-01-01T00:00:00Z",
        "clock": {
            "t0": "2026-01-01T00:00:00Z",
            "marks": [{"name": "Nouméa", "iso": arrival, "lat": -22.27, "lon": 166.44}],
        },
    })
    _seed_fiche("Nouméa", -22.27, 166.44)
    monkeypatch.setenv("NAVIGUIDE_TAVILY_WATCH", "1")
    monkeypatch.setenv("NAVIGUIDE_TAVILY_DAILY_CREDITS", "1")
    llm_budget.record_tavily(1)
    assert llm_budget.allow_tavily() is False
    from main import app
    client = TestClient(app)
    tasks: list = []
    real_create = asyncio.create_task

    def capture(coro, *args, **kwargs):
        code = getattr(coro, "cr_code", None)
        if code is not None and code.co_name == "watch_stop":
            tasks.append(code.co_name)
            coro.close()
            return real_create(asyncio.sleep(0))
        return real_create(coro, *args, **kwargs)

    monkeypatch.setattr(asyncio, "create_task", capture)
    try:
        resp = client.get("/escale?name=Noum%C3%A9a&lat=-22.27&lon=166.44&lang=fr")
        assert resp.status_code == 200
        assert tasks == []
        assert "Nouméa" not in escale_api._INFLIGHT and "noumea" not in escale_api._INFLIGHT
    finally:
        escale_api._INFLIGHT.clear()


def _ready_fiche(name, lat, lon, lang="fr"):
    return {
        "name": name,
        "lat": lat,
        "lon": lon,
        "lang": lang,
        "sections": {"mooring": {"marinas": [{"name": "Quai"}]}},
        "paragraph": {"status": "ready", "text": "Un quai.", "source": "rules"},
        "sources": {},
    }


def test_second_open_same_day_is_cached_without_recompute(monkeypatch):
    """I-13 : la deuxième ouverture du même jour ne relance pas le calcul."""
    escale_api.reset_escale_hot_cache()
    monkeypatch.setattr(escale_api, "escale_day_token", lambda: "2026-10-18")
    calls = []
    fiche = _ready_fiche("Cachejour", 1.23, 4.56)

    async def patched(*_a, **_k):
        calls.append(1)
        return fiche

    monkeypatch.setattr(escale_api, "build_escale", patched)
    from main import app
    client = TestClient(app)
    url = "/escale?name=Cachejour&lat=1.23&lon=4.56&lang=fr"
    first = client.get(url)
    assert first.status_code == 200
    assert first.json()["cached"] is False
    assert calls == [1]
    second = client.get(url)
    assert second.status_code == 200
    assert second.json()["cached"] is True
    assert second.json()["paragraph"]["text"] == "Un quai."
    assert calls == [1]
    key = escale_api.escale_key("Cachejour", 1.23, 4.56, "fr")
    assert key.endswith("|tf3")
    assert "2026-10-18" not in key  # la fiche n'est pas clefée au jour : gardée ESCALE_TTL_S


def test_escale_cache_survives_the_next_utc_day_until_its_ttl(monkeypatch):
    """La fiche (et son paragraphe LLM payant) tient ESCALE_TTL_S, pas un jour ;
    au-delà de la durée de vie, elle est bien recalculée."""
    escale_api.reset_escale_hot_cache()
    days = {"d": "2026-10-18"}
    monkeypatch.setattr(escale_api, "escale_day_token", lambda: days["d"])
    calls = []
    fiche = _ready_fiche("Jourcache", 2.5, 3.5)

    async def patched(*_a, **_k):
        calls.append(days["d"])
        return fiche

    monkeypatch.setattr(escale_api, "build_escale", patched)
    from main import app
    client = TestClient(app)
    url = "/escale?name=Jourcache&lat=2.5&lon=3.5&lang=fr"
    assert client.get(url).json()["cached"] is False
    assert client.get(url).json()["cached"] is True
    days["d"] = "2026-10-19"
    escale_api.reset_escale_hot_cache()  # le lendemain : seul le stock répond
    assert client.get(url).json()["cached"] is True
    assert calls == ["2026-10-18"]
    # Durée de vie dépassée (simulée) : nouveau calcul.
    days["d"] = "2026-10-26"
    escale_api.reset_escale_hot_cache()
    monkeypatch.setattr(escale_api, "ESCALE_TTL_S", -1.0)
    assert client.get(url).json()["cached"] is False
    assert calls == ["2026-10-18", "2026-10-26"]


def test_escale_day_memory_is_keyed_by_utc_day(monkeypatch):
    """Le secours mémoire reste au jour : le lendemain il ne sert plus une fiche d'hier."""
    escale_api.reset_escale_hot_cache()
    days = {"d": "2026-10-18"}
    monkeypatch.setattr(escale_api, "escale_day_token", lambda: days["d"])
    key = escale_api.escale_key("Memjour", 1.0, 2.0, "fr")
    escale_api._remember_escale(key, _ready_fiche("Memjour", 1.0, 2.0))
    assert escale_api._DAY_MEM.get(f"{key}|2026-10-18")
    days["d"] = "2026-10-19"
    assert escale_api._DAY_MEM.get(f"{key}|2026-10-19") is None
    days["d"] = "2026-10-18"
    escale_api._forget_escale(key)
    assert escale_api._DAY_MEM.get(f"{key}|2026-10-18") is None


def test_escale_memory_serves_when_the_store_misses(monkeypatch):
    """Si SQLite n'a pas la fiche, le cache mémoire du jour répond quand même."""
    escale_api.reset_escale_hot_cache()
    monkeypatch.setattr(escale_api, "escale_day_token", lambda: "2026-10-18")
    calls = []
    fiche = _ready_fiche("Memcache", 8.1, 9.2)

    async def patched(*_a, **_k):
        calls.append(1)
        return fiche

    monkeypatch.setattr(escale_api, "build_escale", patched)
    from main import app
    client = TestClient(app)
    url = "/escale?name=Memcache&lat=8.1&lon=9.2&lang=fr"
    assert client.get(url).json()["cached"] is False
    real = pearl_store.kv_get

    def miss(ns, key, *a, **k):
        if ns == "escale":
            return None
        return real(ns, key, *a, **k)

    monkeypatch.setattr(pearl_store, "kv_get", miss)
    second = client.get(url)
    assert second.status_code == 200
    assert second.json()["cached"] is True
    assert second.json()["paragraph"]["text"] == "Un quai."
    assert calls == [1]


def test_parallel_escale_openings_share_one_build(monkeypatch):
    escale_api.reset_escale_hot_cache()
    monkeypatch.setattr(escale_api, "escale_day_token", lambda: "2026-04-02")
    calls = []
    fiche = _ready_fiche("Paral", 11.11, 22.22)

    async def patched(*_a, **_k):
        calls.append(1)
        await asyncio.sleep(0.15)
        return dict(fiche)

    monkeypatch.setattr(escale_api, "build_escale", patched)

    async def burst():
        from httpx import ASGITransport, AsyncClient
        from main import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            return await asyncio.gather(*[
                c.get("/escale?name=Paral&lat=11.11&lon=22.22&lang=fr") for _ in range(6)
            ])

    responses = asyncio.run(burst())
    assert all(r.status_code == 200 for r in responses)
    assert calls == [1]
    assert all(r.json()["paragraph"]["text"] == "Un quai." for r in responses)
