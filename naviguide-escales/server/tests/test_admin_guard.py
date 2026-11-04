"""Sécurité P0 — secret admin partagé, limiteur de débit, PUT officiel anonyme."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import admin_guard
import forecast_cube
import saildocs
import voyage_api
import voyage_store
from admin_guard import ADMIN_HEADER, RateLimiter, cors_origins, reset_limiters

# nginx toujours devant en prod : un appel "public" porte ces en-têtes.
PUBLIC = {"X-Real-IP": "203.0.113.7", "X-Forwarded-For": "203.0.113.7"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_FORECAST_BACKEND", "synthetic")
    monkeypatch.setenv("NAVIGUIDE_VOYAGE_DIR", str(tmp_path / "voyages"))
    monkeypatch.setenv("NAVIGUIDE_FORECAST_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("NAVIGUIDE_GRIB_DIR", str(tmp_path / "grib"))
    monkeypatch.setenv("NAVIGUIDE_GRIB_AUTO", "0")
    monkeypatch.delenv(admin_guard.ADMIN_ENV, raising=False)
    voyage_store._DIR = tmp_path / "voyages"
    forecast_cube.CACHE_DIR = tmp_path / "cache"
    saildocs.GRIB_DIR = tmp_path / "grib"
    reset_limiters()
    from main import app
    test_client = TestClient(app)
    yield test_client
    reset_limiters()


def _official(points=None):
    pts = points or [
        {"lat": 46.15, "lon": -1.16, "cumNm": 0, "filmCum": 0, "jump": False, "nonMaritime": False},
        {"lat": 40.0, "lon": -15.0, "cumNm": 650, "filmCum": 650, "jump": False, "nonMaritime": False},
        {"lat": 14.6, "lon": -61.07, "cumNm": 3350, "filmCum": 3350, "jump": False, "nonMaritime": False},
    ]
    return {
        "t0": "2026-06-01T08:00:00Z",
        "expedition_id": "berry-mappemonde-2026",
        "routeKind": "berry",
        "follow": True,
        "forecast": False,
        "startAt": "la-rochelle",
        "official": True,
        "points": pts,
        "marks": [
            {"name": "La Rochelle", "nm": 0, "filmNm": 0, "lat": 46.15, "lon": -1.16, "index": 0},
            {"name": "Fort-de-France (Martinique)", "nm": 3350, "filmNm": 3350, "lat": 14.6, "lon": -61.07, "index": 2},
        ],
    }


# ── secret ──────────────────────────────────────────────────────────────────

def test_without_secret_local_dev_is_allowed_but_proxied_calls_fail_closed(client):
    # Local direct call (TestClient, no proxy headers) → dev mode, accepted.
    r = client.post("/voyage/official/grib/scan")
    assert r.status_code == 200
    # Same call as seen through nginx → 503 until the secret is configured.
    r = client.post("/voyage/official/grib/scan", headers=PUBLIC)
    assert r.status_code == 503


def test_with_secret_header_is_required_everywhere(client, monkeypatch):
    monkeypatch.setenv(admin_guard.ADMIN_ENV, "top-secret")
    assert client.post("/voyage/official/grib/scan").status_code == 401
    assert client.post("/voyage/official/grib/scan", headers={ADMIN_HEADER: "wrong"}).status_code == 401
    assert client.post("/voyage/official/grib/scan", headers={ADMIN_HEADER: "top-secret"}).status_code == 200
    assert client.post("/voyage/official/grib/refresh", headers=PUBLIC).status_code == 401
    r = client.post("/voyage/official/grib", json={"model": "GFS", "samples": []}, headers=PUBLIC)
    assert r.status_code == 401


def test_polar_upload_is_admin_only(client, monkeypatch):
    monkeypatch.setenv(admin_guard.ADMIN_ENV, "top-secret")
    files = {"file": ("polar.csv", b"twa/tws,6,8\n60,4.1,5.2\n", "text/csv")}
    r = client.post("/api/v1/polar/upload", files=files, data={"expedition_id": "x"}, headers=PUBLIC)
    assert r.status_code == 401


# ── PUT /voyage/official ────────────────────────────────────────────────────

def test_anonymous_put_creates_when_missing_but_never_edits(client, monkeypatch):
    monkeypatch.setenv(admin_guard.ADMIN_ENV, "top-secret")
    body = _official()
    # Disque neuf : un visiteur peut auto-réparer (créer) le voyage officiel.
    r = client.put("/voyage/official", json=body, headers=PUBLIC)
    assert r.status_code == 200
    official = client.get("/voyage/official").json()
    assert len(official["points"]) == 3
    assert official["expedition_id"] == "berry-mappemonde-2026"

    # Visiteur : route plus longue + autre expédition → rien ne change.
    longer = _official(body["points"] + [
        {"lat": 14.0, "lon": -62.0, "cumNm": 3400, "filmCum": 3400, "jump": False, "nonMaritime": False},
    ])
    longer["expedition_id"] = "pirate-2026"
    r = client.put("/voyage/official", json=longer, headers=PUBLIC)
    assert r.status_code == 200
    official = client.get("/voyage/official").json()
    assert len(official["points"]) == 3
    assert official["expedition_id"] == "berry-mappemonde-2026"

    # Admin : la mise à jour passe.
    r = client.put("/voyage/official", json=longer, headers={**PUBLIC, ADMIN_HEADER: "top-secret"})
    assert r.status_code == 200
    official = client.get("/voyage/official").json()
    assert len(official["points"]) == 4
    assert official["expedition_id"] == "pirate-2026"


def test_voyage_payload_bounds(client):
    body = _official()
    body["points"] = body["points"] * 2500  # 7 500 > 6 000
    assert client.post("/voyage", json=body).status_code == 413
    body = _official()
    body["points"][0]["lat"] = 95
    assert client.post("/voyage", json=body).status_code == 400
    body = _official()
    body["points"][0]["lon"] = 1000  # plus d'un tour de globe : faux
    assert client.post("/voyage", json=body).status_code == 400


def test_official_put_accepts_unwrapped_pacific_longitudes(client):
    """Le film déplie les longitudes après l'antiméridien (Papeete → Wallis →
    Nouméa : lon > 180). Refuser ces points cassait le mode Suivre : le PUT
    officiel répondait 400, le client ne lisait jamais l'horloge serveur et
    le bateau restait à Saint-Maur (régression de la sécurité P0)."""
    body = _official([
        {"lat": -17.5, "lon": -149.6, "cumNm": 0, "filmCum": 0, "jump": False, "nonMaritime": False},
        {"lat": -13.3, "lon": 183.8, "cumNm": 1600, "filmCum": 1600, "jump": False, "nonMaritime": False},
        {"lat": -22.3, "lon": 193.4, "cumNm": 2900, "filmCum": 2900, "jump": False, "nonMaritime": False},
    ])
    r = client.put("/voyage/official", json=body)
    assert r.status_code == 200, r.text
    assert r.json().get("clock", {}).get("t0")
    official = client.get("/voyage/official").json()
    assert len(official["points"]) == 3
    assert client.get("/voyage/official/clock").status_code == 200


def test_official_voyage_is_never_recomputed_or_accepted(client):
    client.put("/voyage/official", json=_official())
    vid = voyage_api.OFFICIAL_VOYAGE_ID
    assert client.post(f"/voyage/{vid}/recompute").status_code == 403
    assert client.post(f"/voyage/{vid}/accept").status_code == 403
    assert client.post(f"/voyage/{vid}/reject").status_code == 403
    assert client.post(f"/voyage/{vid}/refresh-forecast", headers=PUBLIC).status_code == 403


# ── limiteur ────────────────────────────────────────────────────────────────

def test_rate_limiter_window_and_global_cap():
    lim = RateLimiter(2, 10.0, global_limit=3)
    assert lim.allow("a", now=0.0)
    assert lim.allow("a", now=1.0)
    assert not lim.allow("a", now=2.0)      # per-key cap
    assert lim.allow("b", now=2.0)
    assert not lim.allow("c", now=3.0)      # global cap (3 hits in the window)
    assert lim.allow("a", now=11.0)         # window slid


def test_story_endpoint_returns_429_beyond_the_ip_budget(client, monkeypatch):
    calls = []

    async def fake_story(body):
        calls.append(body)
        return {"status": "ready", "text": "ok"}

    import main
    monkeypatch.setattr(main, "write_story", fake_story)
    hdr = {**PUBLIC}
    for _ in range(12):
        assert client.post("/ici/story", json={"eventId": "e1"}, headers=hdr).status_code == 200
    r = client.post("/ici/story", json={"eventId": "e1"}, headers=hdr)
    assert r.status_code == 429
    assert r.headers.get("retry-after")
    # Another visitor still has a budget of their own.
    other = {"X-Real-IP": "198.51.100.9", "X-Forwarded-For": "198.51.100.9"}
    assert client.post("/ici/story", json={"eventId": "e1"}, headers=other).status_code == 200
    assert len(calls) == 13


def test_admin_is_exempt_from_rate_limits(client, monkeypatch):
    monkeypatch.setenv(admin_guard.ADMIN_ENV, "top-secret")

    async def fake_story(body):
        return {"status": "ready", "text": "ok"}

    import main
    monkeypatch.setattr(main, "write_story", fake_story)
    hdr = {**PUBLIC, ADMIN_HEADER: "top-secret"}
    for _ in range(20):
        assert client.post("/ici/story", json={"eventId": "e1"}, headers=hdr).status_code == 200


# ── purge ───────────────────────────────────────────────────────────────────

def test_purge_removes_old_simulation_voyages_only(client, tmp_path):
    import os, time
    body = _official()
    body["official"] = False
    old = client.post("/voyage", json=body).json()["voyageId"]
    client.put("/voyage/official", json=_official())
    old_path = voyage_store._path(old)
    stale = time.time() - 9 * 86400
    os.utime(old_path, (stale, stale))
    official_path = voyage_store._path(voyage_api.OFFICIAL_VOYAGE_ID)
    os.utime(official_path, (stale, stale))
    (forecast_cube.CACHE_DIR / old).mkdir(parents=True, exist_ok=True)
    (forecast_cube.CACHE_DIR / old / "cube.json").write_text("{}", encoding="utf-8")

    # A new visitor creation triggers the housekeeping.
    client.post("/voyage", json=body)
    assert not old_path.exists()
    assert not (forecast_cube.CACHE_DIR / old).exists()
    assert official_path.exists()
    assert client.get("/voyage/official").status_code == 200


def test_cors_origins_default_and_env(monkeypatch):
    monkeypatch.delenv("NAVIGUIDE_CORS_ORIGINS", raising=False)
    assert "https://simulator.naviguide.fr" in cors_origins()
    assert cors_origins()[0] == "https://naviguide.fr"
    assert "*" not in cors_origins()
    monkeypatch.setenv("NAVIGUIDE_CORS_ORIGINS", "https://a.example, https://b.example")
    assert cors_origins() == ["https://a.example", "https://b.example"]
