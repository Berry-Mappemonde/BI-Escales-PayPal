"""Le film et l'horloge répondent sans passer par la file du briefing."""
import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient

import film_front
import official_store
from official_store import DiskBackend, OfficialStore

NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
T0 = "2026-05-15T08:00:00Z"


def test_film_returns_the_snapshot(monkeypatch):
    monkeypatch.setattr(
        film_front.official_store,
        "serve_film",
        lambda **kwargs: {"status": "ready", "chapters": [], "lang": kwargs["lang"]},
    )
    client = TestClient(film_front.app)
    res = client.get("/voyage/official/film?lang=en&seconds=0")
    assert res.status_code == 200
    assert res.json()["status"] == "ready"
    assert res.json()["lang"] == "en"


def test_film_missing_lang_defaults_to_french(monkeypatch):
    monkeypatch.setattr(
        film_front.official_store,
        "serve_film",
        lambda **kwargs: {"status": "ready", "chapters": [], "lang": kwargs["lang"]},
    )
    res = TestClient(film_front.app).get("/voyage/official/film")
    assert res.status_code == 200
    assert res.json()["lang"] == "fr"


def test_clock_returns_the_stored_bytes(monkeypatch):
    monkeypatch.setattr(film_front.official_store, "serve_clock_bytes", lambda: b'{"t":1}')
    client = TestClient(film_front.app)
    res = client.get("/voyage/official/clock")
    assert res.status_code == 200
    assert res.json() == {"t": 1}


def test_missing_clock_says_preparing(monkeypatch):
    monkeypatch.setattr(film_front.official_store, "serve_clock_bytes", lambda: None)
    monkeypatch.setattr(film_front.official_store, "nudge_fill_process", lambda: None)
    client = TestClient(film_front.app)
    res = client.get("/voyage/official/clock")
    assert res.status_code == 200
    assert res.json()["status"] == film_front.official_store.PREPARING


def _one_chapter_film():
    plan = {
        "chapters": [{
            "id": "c0",
            "text": (
                "Le 15 mai, Berry-Mappemonde quitte La Rochelle, cap au sud-ouest. "
                "Arrivée à Ajaccio le 26 mai."
            ),
            "tA": T0,
            "tB": T0,
            "fromName": "La Rochelle",
            "toName": "Ajaccio (Corse)",
            "anchors": [{"charIdx": 0, "t": T0}],
        }],
        "source": "rules",
        "chars": 40,
        "targetSeconds": 150,
        "hasWritten": False,
    }
    return {
        "fr": plan,
        "default": plan,
        "variants": {"fr": {"150": plan, "180": plan, "0": plan}},
    }


def _voy():
    return {
        "t0": T0,
        "clock": {"t0": T0, "vertices": [{"lat": 1, "lon": 2, "iso": T0}]},
        "marks": [],
        "points": [{"lat": 1, "lon": 2}],
    }


def test_post_film_calls_the_chain_and_is_not_405(tmp_path, monkeypatch):
    """Le clic Rédigé sur :8011 appelle la chaîne simulée. Aucun crédit."""
    import film_script

    store = OfficialStore(DiskBackend(tmp_path / "film-front-post"), now=lambda: NOW)
    voy = _voy()
    official_store.reset_store()
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "on-demand")
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    store.put("film", _one_chapter_film(), store.family_key("film", voy, NOW))
    calls = {"n": 0}

    async def fake_chain(plan, *, seconds=150, cascade=None, **kwargs):
        calls["n"] += 1
        written = {
            "chapters": list(plan.get("chapters") or []),
            "source": official_store.WRITTEN_SOURCE,
            "hasWritten": True,
            "chars": 40,
            "targetSeconds": seconds,
        }
        return written, None, {
            "super": 1, "ultra_edit": 0, "ultra_judge": 0, "lightning": 0,
            "source": official_store.WRITTEN_SOURCE, "reviewed": False,
        }

    monkeypatch.setattr(film_script, "write_film_chain", fake_chain)

    async def _noop_attach(**_kw):
        return None

    monkeypatch.setattr(official_store, "attach_film_web_context", _noop_attach)
    client = TestClient(film_front.app)

    denied = client.post("/voyage/official/film?lang=fr&seconds=101")
    assert denied.status_code == 422
    assert calls["n"] == 0

    first = client.post("/voyage/official/film?lang=fr&seconds=150")
    assert first.status_code != 405
    assert first.status_code == 200
    body = first.json()
    # Async contract: first POST returns writing=True, hasWritten=True immediately
    # (In tests, the task runs synchronously, so calls["n"] becomes 1 immediately)
    assert body["writing"] is True
    assert body["hasWritten"] is False
    assert body["status"] == "writing"

    # Second POST: task completed (sync in test), so cached written film is served
    second = client.post("/voyage/official/film?lang=fr&seconds=150")
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["hasWritten"] is True
    assert second_body["status"] == "ready"
    # calls["n"] should not increase on second POST (no duplicate)
    assert calls["n"] == 1

    # Poll GET — write has completed (sync in test)
    got = client.get("/voyage/official/film?lang=fr&seconds=150&style=written")
    assert got.status_code == 200
    assert got.json()["hasWritten"] is True
    assert got.json()["source"] == official_store.WRITTEN_SOURCE
    assert calls["n"] == 1


def test_post_film_rate_limit_on_this_process(monkeypatch):
    """Le limiteur du clic vit sur le processus qui reçoit vraiment le POST."""
    import admin_guard

    admin_guard.reset_limiters()

    async def fake_write(lang="fr", seconds=150, **_kwargs):
        return {
            "status": "ready", "hasWritten": False, "chapters": [],
            "source": "rules", "chars": 0, "targetSeconds": seconds,
        }

    monkeypatch.setattr(film_front.official_store, "write_film_on_click", fake_write)
    client = TestClient(film_front.app)
    headers = {"X-Real-IP": "203.0.113.77", "X-Forwarded-For": "203.0.113.77"}
    for _ in range(12):
        res = client.post("/voyage/official/film?lang=fr&seconds=150", headers=headers)
        assert res.status_code == 200
    blocked = client.post("/voyage/official/film?lang=fr&seconds=150", headers=headers)
    assert blocked.status_code == 429
    assert blocked.headers.get("retry-after")
    admin_guard.reset_limiters()


def test_main_post_film_generation_exception_has_unavailable_reason(monkeypatch):
    import main
    import official_store as main_official_store

    async def fail_write(**_kwargs):
        raise RuntimeError("synthetic generation failure")

    monkeypatch.setattr(main_official_store, "start_film_write", fail_write)
    monkeypatch.setattr(main_official_store, "kick_worker", lambda: None)
    response = asyncio.run(main.post_official_film_write(lang="fr", seconds=150))
    assert response["status"] == "preparing"
    assert response["reason"] == "all-providers-failed"
