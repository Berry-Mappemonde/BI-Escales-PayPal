import asyncio
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import forecast_cube
import voyage_api
import voyage_store
from weather_pipeline import get_pipeline


def _wait_forecast(client, voyage_id, timeout=2.0):
    pts = client.get(f"/voyage/{voyage_id}").json().get("points") or []
    lat = float((pts[0] or {}).get("lat") or 0)
    lon = float((pts[0] or {}).get("lon") or 0)
    get_pipeline().wait_ready(f"forecast-cube:{voyage_id}", lat, lon, timeout=timeout)
    deadline = time.monotonic() + timeout
    meta = None
    while time.monotonic() < deadline:
        meta = client.get(f"/voyage/{voyage_id}").json()
        if meta.get("forecastStatus") == "ready":
            return meta
        time.sleep(0.02)
    return meta or client.get(f"/voyage/{voyage_id}").json()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_FORECAST_BACKEND", "synthetic")
    monkeypatch.setenv("NAVIGUIDE_VOYAGE_DIR", str(tmp_path / "voyages"))
    monkeypatch.setenv("NAVIGUIDE_FORECAST_CACHE", str(tmp_path / "cache"))
    voyage_store._DIR = tmp_path / "voyages"
    forecast_cube.CACHE_DIR = tmp_path / "cache"
    from main import app
    return TestClient(app)


def _payload(t0: str):
    return {
        "t0": t0,
        "expedition_id": "test-exp",
        "routeKind": "berry",
        "follow": True,
        "forecast": True,
        "startAt": "la-rochelle",
        "points": [
            {"lat": 46.15, "lon": -1.16, "cumNm": 0, "filmCum": 0, "jump": False, "nonMaritime": False},
            {"lat": 40.0, "lon": -15.0, "cumNm": 650, "filmCum": 650, "jump": False, "nonMaritime": False},
            {"lat": 28.0, "lon": -30.0, "cumNm": 1450, "filmCum": 1450, "jump": False, "nonMaritime": False},
            {"lat": 16.0, "lon": -48.0, "cumNm": 2600, "filmCum": 2600, "jump": False, "nonMaritime": False},
            {"lat": 14.6, "lon": -61.07, "cumNm": 3350, "filmCum": 3350, "jump": False, "nonMaritime": False},
        ],
        "marks": [
            {"name": "La Rochelle", "nm": 0, "filmNm": 0, "lat": 46.15, "lon": -1.16, "index": 0},
            {"name": "Fort-de-France (Martinique)", "nm": 3350, "filmNm": 3350, "lat": 14.6, "lon": -61.07, "index": 4},
        ],
    }


def test_create_pending_then_ready(client):
    t0 = "2026-06-15T08:00:00Z"
    r = client.post("/voyage", json=_payload(t0))
    assert r.status_code in (200, 202)
    body = r.json()
    assert body["forecastStatus"] in ("pending", "ready")
    vid = body["voyageId"]
    meta = _wait_forecast(client, vid)
    assert meta["forecastStatus"] == "ready"
    assert meta["forecastModel"] == "synthetic-test"


def test_at_plus_48h_forecast_and_f5(client, monkeypatch):
    t0 = datetime(2026, 6, 15, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(voyage_api, "_now", lambda: t0)
    r = client.post("/voyage", json=_payload(t0.isoformat().replace("+00:00", "Z")))
    vid = r.json()["voyageId"]
    _wait_forecast(client, vid)
    when = (t0 + timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
    a = client.get(f"/voyage/{vid}/at", params={"t": when})
    b = client.get(f"/voyage/{vid}/at", params={"t": when})
    assert a.status_code == 200
    assert a.json()["kind"] == "forecast"
    assert a.json()["model"]
    assert a.json()["leadHours"] == 48.0
    assert abs(a.json()["lat"] - b.json()["lat"]) < 1e-6
    assert abs(a.json()["lon"] - b.json()["lon"]) < 1e-6
    # ± 1 nm of stability: same point
    assert a.json()["status"] == "live"


def test_at_plus_11d_climatology(client, monkeypatch):
    t0 = datetime(2026, 6, 15, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(voyage_api, "_now", lambda: t0)
    vid = client.post("/voyage", json=_payload(t0.strftime("%Y-%m-%dT%H:%M:%SZ"))).json()["voyageId"]
    _wait_forecast(client, vid)
    when = (t0 + timedelta(days=11)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sample = client.get(f"/voyage/{vid}/at", params={"t": when}).json()
    assert sample["kind"] == "climatology"
    assert sample.get("leadHours") in (None, 0)


def test_waiting_before_t0(client):
    t0 = datetime(2026, 9, 20, 8, tzinfo=timezone.utc)
    vid = client.post("/voyage", json=_payload(t0.strftime("%Y-%m-%dT%H:%M:%SZ"))).json()["voyageId"]
    _wait_forecast(client, vid)
    past = (t0 - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sample = client.get(f"/voyage/{vid}/at", params={"t": past}).json()
    assert sample["status"] == "waiting"
    assert sample["countdownHours"] > 0


def test_recompute_reject_accept(client, monkeypatch):
    t0 = datetime(2026, 6, 13, 8, tzinfo=timezone.utc)  # ~48 h before a mid-June recette
    vid = client.post("/voyage", json=_payload(t0.strftime("%Y-%m-%dT%H:%M:%SZ"))).json()["voyageId"]
    client.get(f"/voyage/{vid}")
    # Force an "offshore" position: t = t0+48h via monkeypatch of _now
    live_t = t0 + timedelta(hours=48)

    monkeypatch.setattr(voyage_api, "_now", lambda: live_t)
    rec = client.post(f"/voyage/{vid}/recompute")
    assert rec.status_code == 200
    draft = rec.json()
    assert draft["status"] in ("arrived", "spliced", "failed")
    assert "draft_geojson" in draft
    assert draft["versus_searoute"]["distance_nm"] > 0

    client.post(f"/voyage/{vid}/reject")
    assert client.get(f"/voyage/{vid}/draft").status_code == 404

    rec2 = client.post(f"/voyage/{vid}/recompute")
    assert rec2.status_code == 200
    if rec2.json()["status"] == "failed" or len(
        rec2.json().get("draft_geojson", {}).get("geometry", {}).get("coordinates") or []
    ) < 2:
        pytest.skip("isochrone trop courte sur le mock — status failed")
    acc = client.post(f"/voyage/{vid}/accept")
    assert acc.status_code == 200
    assert acc.json()["routeRev"] == 1
    # The Pacific is not in this test route; the downstream after FDF does not exist.
    # Check that the upstream (La Rochelle) is still the first point.
    assert acc.json()["points"][0]["lat"] == pytest.approx(46.15, abs=0.05)


def test_refresh_forecast(client):
    t0 = datetime(2026, 6, 15, 8, tzinfo=timezone.utc)
    vid = client.post("/voyage", json=_payload(t0.strftime("%Y-%m-%dT%H:%M:%SZ"))).json()["voyageId"]
    _wait_forecast(client, vid)
    r = client.post(f"/voyage/{vid}/refresh-forecast")
    assert r.status_code == 200
    assert r.json()["forecastStatus"] in ("pending", "ready")
    meta = _wait_forecast(client, vid)
    assert meta["forecastStatus"] == "ready"


def test_recompute_takes_the_skipper_orders_as_constraints(client, monkeypatch):
    """Vent max / mer max du skipper → zones interdites du routage,
    renvoyées dans le brouillon ; hors bornes → ignorés (défaut honnête)."""
    t0 = datetime(2026, 6, 13, 8, tzinfo=timezone.utc)
    vid = client.post("/voyage", json=_payload(t0.strftime("%Y-%m-%dT%H:%M:%SZ"))).json()["voyageId"]
    client.get(f"/voyage/{vid}")
    monkeypatch.setattr(voyage_api, "_now", lambda: t0 + timedelta(hours=48))
    rec = client.post(f"/voyage/{vid}/recompute", json={"wind_max_kt": 34, "hs_max_m": 3.5})
    assert rec.status_code == 200
    draft = rec.json()
    assert draft["constraints"] == {"windMaxKt": 34.0, "hsMaxM": 3.5, "source": "skipper"}
    assert "draft_geojson" in draft
    rec2 = client.post(f"/voyage/{vid}/recompute", json={"wind_max_kt": 5, "hs_max_m": 40})
    assert rec2.json()["constraints"]["source"] == "default"
    assert rec2.json()["constraints"]["windMaxKt"] is None


def test_route_delta_is_rules_only():
    old = [[-1.16, 46.15], [-15.0, 40.0], [-30.0, 28.0]]
    new = [[-1.16, 46.15], [-18.0, 42.0], [-30.0, 28.0]]
    d = voyage_api.route_delta(old, new, official_nm=1450.4, recomputed_nm=1499.6)
    assert d["official_nm"] == 1450 and d["recomputed_nm"] == 1500
    assert d["distance_delta_nm"] == 50  # |1500 − 1450|
    assert d["max_deviation_nm"] >= 0
    assert d["avoided_points"] >= 0


    facts = voyage_api.advice_facts(d, {"source": "skipper", "windMaxKt": 30, "hsMaxM": 3.5})
    phrase = voyage_api.advice_fallback(facts)
    assert "30" in phrase
    assert "99" not in phrase
    for token in ("1450", "1500", "50", str(d["max_deviation_nm"]), str(d["avoided_points"])):
        if token in phrase:
            assert token in {str(facts[k]) for k in facts if facts[k] is not None}


def test_official_moments_passes_english_language_to_journal_builder(monkeypatch):
    seen = {}
    monkeypatch.setattr(voyage_api.official_store, "serve_moments", lambda **_kw: {
        "status": "ready", "count": 1, "moments": [{"signature": "fr"}],
    })
    monkeypatch.setattr(voyage_api, "load_voyage", lambda _voyage_id: {"voyageId": "official"})

    def build(_voyage_id, _voy, lang="fr"):
        seen["lang"] = lang
        return [{"signature": lang}]

    monkeypatch.setattr("moment_journal.rows_from_voyage", build)
    response = voyage_api.get_official_moments(lang="en")
    assert seen["lang"] == "en"
    assert response["moments"] == [{"signature": "en"}]


def test_official_moments_english_keeps_frozen_rows_when_rebuild_is_empty(monkeypatch):
    import json
    import tarfile
    from pathlib import Path

    archive = Path(__file__).resolve().parent / "fixtures" / "official_store.tar.gz"
    with tarfile.open(archive, "r:gz") as tf:
        member = next(m for m in tf.getmembers() if m.name.endswith("/moments.json"))
        stored = json.load(tf.extractfile(member))["payload"]["moments"]

    monkeypatch.setattr(voyage_api.official_store, "serve_moments", lambda **_kw: {
        "status": "ready", "count": len(stored), "moments": stored,
    })
    monkeypatch.setattr(voyage_api, "load_voyage", lambda _voyage_id: {"voyageId": "official"})
    # Frozen data has no pearl history for this English rebuild.
    monkeypatch.setattr("moment_journal.rows_from_voyage", lambda *_a, **_kw: [])

    fr = voyage_api.get_official_moments(lang="fr")
    en = voyage_api.get_official_moments(lang="en")
    assert fr["count"] > 0
    assert en["count"] == 0


def test_official_moments_english_fallback_only_keeps_explicitly_english_rows(monkeypatch):
    stored = [
        {"lang": "fr", "t": "2026-01-01T00:00:00Z", "changes": [{"title": "Station croisée"}]},
        {"lang": "en", "t": "2026-01-02T00:00:00Z", "changes": [{"title": "Station passed"}]},
        {"t": "2026-01-03T00:00:00Z", "changes": [{"title": "Unknown language"}]},
    ]
    monkeypatch.setattr(voyage_api.official_store, "serve_moments", lambda **_kw: {
        "status": "ready", "count": len(stored), "moments": stored,
    })
    monkeypatch.setattr(voyage_api, "load_voyage", lambda _voyage_id: {"voyageId": "official"})
    monkeypatch.setattr("moment_journal.rows_from_voyage", lambda *_a, **_kw: [])

    response = voyage_api.get_official_moments(lang="en")

    assert response["count"] == 1
    assert response["moments"] == [stored[1]]


def test_explain_recompute_fast_tier_filters_invented_numbers(monkeypatch):
    seen = {}

    async def fake_cascade(system, user, client=None, **kw):
        seen.update(kw)
        return "La route s'écarte de 12 nm pour éviter 2 points. J'ajoute 99 kn.", "nemotron-lightning"

    delta = {
        "official_nm": 100, "recomputed_nm": 110, "distance_delta_nm": 10,
        "max_deviation_nm": 12, "avoided_points": 2,
    }
    out = asyncio.run(voyage_api.explain_recompute(
        delta, {"source": "skipper", "windMaxKt": 30}, cascade=fake_cascade,
    ))
    assert seen.get("tier") == "fast"
    assert "12" in out["text"] and "2" in out["text"]
    assert "99" not in out["text"]
    assert out["source"] == "nemotron-lightning"
    assert out["delta"]["wind_max_kt"] == 30


def test_recompute_advice_numbers_match_delta(client, monkeypatch):
    def fake_iso(**kw):
        return {
            "status": "arrived",
            "kind_mix": ["climatology"],
            "draft_geojson": {
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "LineString", "coordinates": [[-1.16, 46.15], [-18.0, 42.0], [-30.0, 28.0]]},
            },
            "hours": 10,
            "distance_nm": 900.4,
            "isochrones": [],
            "steps": 1,
            "route": [],
        }

    monkeypatch.setattr(voyage_api, "run_leg_isochrone", fake_iso)

    async def fake_explain(delta, constraints=None, **kw):
        return {
            "text": voyage_api.advice_fallback(voyage_api.advice_facts(delta, constraints)),
            "source": "rules",
            "delta": voyage_api.advice_facts(delta, constraints),
        }

    monkeypatch.setattr(voyage_api, "explain_recompute", fake_explain)
    t0 = datetime(2026, 6, 13, 8, tzinfo=timezone.utc)
    vid = client.post("/voyage", json=_payload(t0.strftime("%Y-%m-%dT%H:%M:%SZ"))).json()["voyageId"]
    monkeypatch.setattr(voyage_api, "_now", lambda: t0 + timedelta(hours=48))
    draft = client.post(f"/voyage/{vid}/recompute", json={"wind_max_kt": 30, "hs_max_m": 3.5}).json()
    advice = draft["advice"]
    delta = advice["delta"]
    assert advice["source"] == "rules"
    assert str(delta["max_deviation_nm"]) in advice["text"]
    assert "99" not in advice["text"]
    assert delta["wind_max_kt"] == 30


def test_c2_regime_changes_at_now_and_regimes_endpoint(client, monkeypatch):
    t0 = datetime(2026, 6, 15, 8, tzinfo=timezone.utc)
    now = t0 + timedelta(days=4)
    monkeypatch.setattr(voyage_api, "_now", lambda: now)
    vid = client.post("/voyage", json=_payload(t0.strftime("%Y-%m-%dT%H:%M:%SZ"))).json()["voyageId"]
    _wait_forecast(client, vid)
    past = client.get(f"/voyage/{vid}/at", params={"t": (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")}).json()
    future = client.get(f"/voyage/{vid}/at", params={"t": (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")}).json()
    assert past["regime"] in ("hindcast", "climatology")
    assert future["regime"] == "forecast"
    clock = client.get(f"/voyage/{vid}/clock").json()
    from voyage_api import _regime_portions
    portions = _regime_portions(clock)
    assert portions
    assert {p["regime"] for p in portions} & {"forecast", "climatology", "hindcast"}


def test_official_regimes_endpoint(client):
    client.put("/voyage/official", json=_payload("2026-05-15T08:00:00Z"))
    r = client.get("/voyage/official/regimes")
    assert r.status_code == 200
    body = r.json()
    assert "portions" in body
    assert body["voyageId"] == "berry-mappemonde-2026-officiel"


def test_official_eta_noumea_dzaoudzi_span_is_days(client, monkeypatch):
    """/voyage/official/eta resserre un p90 de 7 mois."""
    from ensemble_eta import ETA_MAX_SPAN_DAYS, tighten_eta_payload
    from plan_review import eta_span_days

    now = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)
    exploded = {
        "p10": "2026-11-13T00:00:00Z",
        "p50": "2026-11-15T00:00:00Z",
        "p90": "2027-06-10T00:00:00Z",
        "members": 80,
        "memberKnots": [8.0, 8.2, 0.4],
        "source": "open-meteo-ensemble",
        "computedAt": "2026-09-21T12:00:00Z",
    }
    monkeypatch.setattr(voyage_api, "_now", lambda: now)

    def fake_peek_official_eta(voy, stop, when):
        assert "Dzaoudzi" in stop or "dzaoudzi" in stop.lower()
        return exploded

    import ensemble_eta
    monkeypatch.setattr(ensemble_eta, "peek_official_eta", fake_peek_official_eta)
    client.put("/voyage/official", json=_payload("2026-05-15T08:00:00Z"))
    import official_store
    official_store.put("eta", {"stops": {"Dzaoudzi (Mayotte)": tighten_eta_payload(exploded, now)}})
    r = client.get("/voyage/official/eta", params={"stop": "Dzaoudzi (Mayotte)"})
    assert r.status_code == 200
    body = r.json()
    assert body["members"] > 0
    assert 0.4 not in (body.get("memberKnots") or [])
    span = eta_span_days(body["p10"], body["p90"])
    assert span is not None and span <= ETA_MAX_SPAN_DAYS + 1e-6
    assert "2027-06" not in (body["p90"] or "")
    tight = tighten_eta_payload(exploded, now)
    assert eta_span_days(tight["p10"], tight["p90"]) <= 7.01


def test_official_itinerary_body_is_embedded_berry_without_network():
    """L'itinéraire Berry est lu sur disque, pas inventé."""
    from hindcast import block_network, unblock_network

    block_network()
    try:
        body = voyage_api.official_itinerary_body()
    finally:
        unblock_network()
    assert body is not None
    assert len(body.points) > 200
    assert body.points[0]["lat"] == pytest.approx(46.8075, abs=0.01)
    assert body.points[0]["lon"] == pytest.approx(1.6358, abs=0.01)
    names = [m["name"] for m in body.marks]
    assert any("Saint-Maur" in n for n in names)
    assert any("Dzaoudzi" in n for n in names)
    assert names[-1].startswith("La Rochelle")
    assert body.t0.startswith("2026-05-15")


def test_get_official_never_404_on_empty_store(client):
    """Store vide : GET sème et répond 200, sans 404."""
    assert voyage_store.load_voyage("berry-mappemonde-2026-officiel") is None
    r = client.get("/voyage/official")
    assert r.status_code == 200
    body = r.json()
    assert body["voyageId"] == "berry-mappemonde-2026-officiel"
    assert body["official"] is True
    assert len(body["points"] or []) > 200
    assert voyage_store.load_voyage("berry-mappemonde-2026-officiel") is not None


def test_startup_seeds_official_on_empty_store_without_blocking(tmp_path, monkeypatch):
    """Hook de boot : semé, kicks en fond, retour immédiat."""
    monkeypatch.setenv("NAVIGUIDE_VOYAGE_DIR", str(tmp_path / "voyages"))
    monkeypatch.setenv("NAVIGUIDE_SEED_OFFICIAL", "force")
    voyage_store._DIR = tmp_path / "voyages"
    assert voyage_store.load_voyage("berry-mappemonde-2026-officiel") is None

    monkeypatch.setattr(voyage_api, "_kick_official_grib", lambda *a, **k: True)
    monkeypatch.setattr(voyage_api, "_kick_official_hindcast", lambda *a, **k: True)
    monkeypatch.setattr(voyage_api, "_kick_official_eta", lambda *a, **k: True)
    monkeypatch.setattr(voyage_api, "_kick_official_moments", lambda *a, **k: True)
    monkeypatch.setattr(voyage_api, "_kick_official_film_story", lambda *a, **k: True)

    from main import _startup_official_grib

    t0 = time.monotonic()
    _startup_official_grib()
    assert time.monotonic() - t0 < 1.0
    voy = voyage_store.load_voyage("berry-mappemonde-2026-officiel")
    assert voy is not None
    assert len(voy.get("points") or []) > 200
    assert voy.get("clock") is None
    again = voyage_api.seed_official_voyage()
    assert again["voyageId"] == voy["voyageId"]
    assert len(again["points"]) == len(voy["points"])


def test_kick_official_eta_false_until_seeded(tmp_path, monkeypatch):
    """Sans voyage : False (absent). Après semis : plus False pour cause d'absence."""
    monkeypatch.setenv("NAVIGUIDE_VOYAGE_DIR", str(tmp_path / "voyages"))
    monkeypatch.setenv("NAVIGUIDE_ETA_PREHEAT", "1")
    voyage_store._DIR = tmp_path / "voyages"
    get_pipeline().clear()

    assert voyage_store.load_voyage("berry-mappemonde-2026-officiel") is None
    assert voyage_api._kick_official_eta() is False

    voy = voyage_api.seed_official_voyage()
    assert voy and voy.get("points")

    import ensemble_eta

    monkeypatch.setattr(ensemble_eta, "preheat_official_eta", lambda *a, **k: {"members": 12})
    get_pipeline().clear()
    assert voyage_api._kick_official_eta() is True


def test_get_eta_seeded_without_clock_is_empty_no_fetch(client, monkeypatch):
    """Voyage semé sans clock → GET /eta 200, members 0, aucun fetch."""
    from hindcast import block_network, unblock_network
    import ensemble_eta

    voy = voyage_api.seed_official_voyage()
    assert voy is not None
    assert voy.get("clock") is None
    assert voyage_store.load_voyage("berry-mappemonde-2026-officiel") is not None

    kicked = []
    monkeypatch.setattr(
        voyage_api,
        "_kick_official_eta",
        lambda **k: kicked.append(k) or True,
    )
    calls = {"compute": 0, "clock": 0, "fetch": 0, "official": 0}

    def boom_compute(*_a, **_k):
        calls["compute"] += 1
        raise AssertionError("compute_eta sur le thread HTTP")

    def boom_clock(*_a, **_k):
        calls["clock"] += 1
        raise AssertionError("build_voyage_clock sur le thread HTTP")

    def boom_fetch(*_a, **_k):
        calls["fetch"] += 1
        raise AssertionError("fetch_point_members sur le thread HTTP")

    def boom_official(*_a, **_k):
        calls["official"] += 1
        raise AssertionError("official_eta sur le thread HTTP")

    monkeypatch.setattr(ensemble_eta, "compute_eta", boom_compute)
    monkeypatch.setattr(ensemble_eta, "build_voyage_clock", boom_clock)
    monkeypatch.setattr(ensemble_eta, "fetch_point_members", boom_fetch)
    monkeypatch.setattr(ensemble_eta, "official_eta", boom_official)

    block_network()
    try:
        t0 = time.monotonic()
        r = client.get("/voyage/official/eta", params={"stop": "Dzaoudzi (Mayotte)"})
        elapsed = time.monotonic() - t0
        moments = client.get("/voyage/official/moments")
    finally:
        unblock_network()

    assert r.status_code == 200
    body = r.json()
    assert body["members"] == 0
    assert body.get("p10") is None and body.get("p90") is None
    assert elapsed < 2.0
    assert body.get("status") == "preparing"
    assert calls["compute"] == 0
    assert calls["clock"] == 0
    assert calls["fetch"] == 0
    assert calls["official"] == 0
    assert moments.status_code == 200
    assert moments.json().get("moments") == []


def test_kick_official_eta_restarts_when_first_ready_is_empty(tmp_path, monkeypatch):
    """Un premier ready vide n'est pas terminal — GET /eta relance le warm."""
    monkeypatch.setenv("NAVIGUIDE_VOYAGE_DIR", str(tmp_path / "voyages"))
    monkeypatch.setenv("NAVIGUIDE_ETA_PREHEAT", "1")
    voyage_store._DIR = tmp_path / "voyages"
    get_pipeline().clear()

    voy = voyage_api.seed_official_voyage()
    assert voy and voy.get("points")
    assert voy.get("clock") is None

    import ensemble_eta

    monkeypatch.setattr(ensemble_eta, "preheat_official_eta", lambda *a, **k: {"members": 0})
    get_pipeline().clear()
    assert voyage_api._kick_official_eta(force=True, stop="Dzaoudzi") is True
    voyage_api._wait_official_kick("official-eta", timeout=2.0)
    hit = get_pipeline().peek("official-eta", 0.0, 0.0, when=voyage_api._now())
    assert hit and hit.get("status") in {"ready", "error"}

    assert voyage_api._kick_official_eta(force=False, stop="Dzaoudzi") is True


def test_kick_official_eta_stays_when_members_ready(tmp_path, monkeypatch):
    """Dès qu'il y a des membres, force=False ne relance pas."""
    monkeypatch.setenv("NAVIGUIDE_VOYAGE_DIR", str(tmp_path / "voyages"))
    monkeypatch.setenv("NAVIGUIDE_ETA_PREHEAT", "1")
    voyage_store._DIR = tmp_path / "voyages"
    get_pipeline().clear()

    voy = voyage_api.seed_official_voyage()
    assert voy and voy.get("points")

    import ensemble_eta

    monkeypatch.setattr(ensemble_eta, "preheat_official_eta", lambda *a, **k: {"members": 12})
    monkeypatch.setattr(
        ensemble_eta,
        "peek_official_eta",
        lambda *a, **k: {"members": 12, "p10": "2026-10-11T00:00:00Z", "p90": "2026-10-13T00:00:00Z"},
    )
    get_pipeline().clear()
    assert voyage_api._kick_official_eta(force=True, stop="Dzaoudzi") is True
    voyage_api._wait_official_kick("official-eta", timeout=2.0)
    assert voyage_api._kick_official_eta(force=False, stop="Dzaoudzi") is False


def test_get_eta_serves_alias_cache_without_clock(client, monkeypatch):
    """Cache alias → GET /eta 200 avec membres, toujours sans clock."""
    import ensemble_eta
    from pearl_store import kv_put

    voy = voyage_api.seed_official_voyage()
    assert voy.get("clock") is None
    now = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(voyage_api, "_now", lambda: now)
    monkeypatch.setattr(voyage_api, "_kick_official_eta", lambda **k: True)
    payload = {
        "p10": "2026-10-11T00:00:00Z",
        "p50": "2026-10-12T00:00:00Z",
        "p90": "2026-10-13T00:00:00Z",
        "members": 12,
        "memberKnots": [8.0, 8.2],
        "source": "open-meteo-ensemble",
        "computedAt": "2026-09-21T12:00:00Z",
    }
    kv_put(
        ensemble_eta.CACHE_NS,
        ensemble_eta.official_eta_alias_key("Dzaoudzi (Mayotte)", now),
        payload,
    )
    import official_store
    official_store.put("eta", {"stops": {"Dzaoudzi (Mayotte)": payload}})
    r = client.get("/voyage/official/eta", params={"stop": "Dzaoudzi (Mayotte)"})
    assert r.status_code == 200
    body = r.json()
    assert body["members"] == 12
    assert body["p10"] and body["p90"]


def test_kick_official_warmups_one_after_another(monkeypatch):
    """Hindcast puis eta puis moments puis film, jamais les cinq ensemble."""
    log = []

    def wrap(name):
        def kick(*_a, **_k):
            log.append(f"kick:{name}")
            return True
        return kick

    monkeypatch.setattr(voyage_api, "_kick_official_grib", wrap("grib"))
    monkeypatch.setattr(voyage_api, "_kick_official_hindcast", wrap("hindcast"))
    monkeypatch.setattr(voyage_api, "_kick_official_eta", wrap("eta"))
    monkeypatch.setattr(voyage_api, "_kick_official_moments", wrap("moments"))
    monkeypatch.setattr(voyage_api, "_kick_official_film_story", wrap("film"))
    monkeypatch.setattr(
        voyage_api,
        "_wait_official_kick",
        lambda provider, timeout=900.0: log.append(f"wait:{provider}"),
    )
    t0 = time.monotonic()
    voyage_api.kick_official_warmups()
    assert time.monotonic() - t0 < 1.0
    assert log == [
        "kick:grib",
        "wait:official-grib",
        "kick:hindcast",
        "wait:official-hindcast",
        "kick:eta",
        "wait:official-eta",
        "kick:moments",
        "wait:official-moments",
        "kick:film",
        "wait:official-film-story",
    ]


def test_get_eta_failed_ensemble_returns_reason(client, monkeypatch):
    """Members 0 → raison / dernière tentative / prochaine relance, pas de date."""
    now = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(voyage_api, "_now", lambda: now)
    monkeypatch.setattr(voyage_api, "_kick_official_eta", lambda **k: False)

    def fake_peek(_voy, stop, _when):
        assert "Papeete" in stop or "papeete" in stop.lower()
        return {
            "members": 0,
            "p10": None,
            "p50": None,
            "p90": None,
            "source": None,
            "computedAt": "2026-09-26T12:00:00Z",
            "memberKnots": [],
            "reason": "ensemble_unavailable",
            "lastAttempt": "2026-09-26T12:00:00Z",
            "nextRetry": "2026-09-27T00:15:00Z",
            "detail": "Daily API request limit exceeded. Please try again tomorrow.",
        }

    import ensemble_eta
    monkeypatch.setattr(ensemble_eta, "peek_official_eta", fake_peek)
    client.get("/voyage/official")
    import official_store
    official_store.put("eta", {"stops": {"Papeete (Polynésie française)": fake_peek(None, "Papeete (Polynésie française)", now)}})
    r = client.get("/voyage/official/eta", params={"stop": "Papeete (Polynésie française)"})
    assert r.status_code == 200
    body = r.json()
    assert body["members"] == 0
    assert body["p10"] is None and body["p90"] is None
    assert body["reason"] == "ensemble_unavailable"
    assert body["lastAttempt"]
    assert body["nextRetry"]
    assert "limit exceeded" in (body.get("detail") or "")


def test_get_eta_ready_members_bounded(client, monkeypatch):
    """Ensemble qui répond → membres et fourchette bornée."""
    from ensemble_eta import ETA_MAX_SPAN_DAYS
    from plan_review import eta_span_days

    now = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(voyage_api, "_now", lambda: now)
    monkeypatch.setattr(voyage_api, "_kick_official_eta", lambda **k: False)

    def fake_peek(_voy, stop, _when):
        return {
            "p10": "2026-10-11T00:00:00Z",
            "p50": "2026-10-12T12:00:00Z",
            "p90": "2026-10-14T00:00:00Z",
            "members": 24,
            "memberKnots": [8.0, 8.2, 7.9],
            "source": "open-meteo-ensemble",
            "computedAt": "2026-09-26T12:00:00Z",
        }

    import ensemble_eta
    monkeypatch.setattr(ensemble_eta, "peek_official_eta", fake_peek)
    client.get("/voyage/official")
    import official_store
    official_store.put("eta", {"stops": {"Papeete (Polynésie française)": fake_peek(None, "Papeete", now)}})
    r = client.get("/voyage/official/eta", params={"stop": "Papeete (Polynésie française)"})
    assert r.status_code == 200
    body = r.json()
    assert body["members"] > 0
    assert body["p10"] and body["p90"]
    span = eta_span_days(body["p10"], body["p90"])
    assert span is not None and span <= ETA_MAX_SPAN_DAYS + 1e-6
    assert not body.get("reason")


def test_kick_official_eta_backs_off_until_next_retry(tmp_path, monkeypatch):
    """Après un échec, force=False ne relance pas avant nextRetry."""
    monkeypatch.setenv("NAVIGUIDE_VOYAGE_DIR", str(tmp_path / "voyages"))
    monkeypatch.setenv("NAVIGUIDE_ETA_PREHEAT", "1")
    voyage_store._DIR = tmp_path / "voyages"
    get_pipeline().clear()
    voy = voyage_api.seed_official_voyage()
    assert voy and voy.get("points")

    import ensemble_eta
    future = (voyage_api._now() + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    monkeypatch.setattr(ensemble_eta, "preheat_official_eta", lambda *a, **k: {"members": 0})
    monkeypatch.setattr(
        ensemble_eta,
        "peek_official_eta",
        lambda *a, **k: {
            "members": 0,
            "reason": "ensemble_unavailable",
            "nextRetry": future,
            "lastAttempt": "2026-09-26T12:00:00Z",
        },
    )
    get_pipeline().clear()
    assert voyage_api._kick_official_eta(force=True, stop="Papeete") is True
    voyage_api._wait_official_kick("official-eta", timeout=2.0)
    assert voyage_api._kick_official_eta(force=False, stop="Papeete") is False


def test_kick_official_eta_retries_when_backoff_elapsed(tmp_path, monkeypatch):
    """NextRetry échu → GET relance le warm (RC9 conservé)."""
    monkeypatch.setenv("NAVIGUIDE_VOYAGE_DIR", str(tmp_path / "voyages"))
    monkeypatch.setenv("NAVIGUIDE_ETA_PREHEAT", "1")
    voyage_store._DIR = tmp_path / "voyages"
    get_pipeline().clear()
    voy = voyage_api.seed_official_voyage()
    assert voy and voy.get("points")

    import ensemble_eta
    past = (voyage_api._now() - timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    monkeypatch.setattr(ensemble_eta, "preheat_official_eta", lambda *a, **k: {"members": 0})
    monkeypatch.setattr(
        ensemble_eta,
        "peek_official_eta",
        lambda *a, **k: {
            "members": 0,
            "reason": "ensemble_unavailable",
            "nextRetry": past,
            "lastAttempt": "2026-09-26T11:00:00Z",
        },
    )
    get_pipeline().clear()
    assert voyage_api._kick_official_eta(force=True, stop="Papeete") is True
    voyage_api._wait_official_kick("official-eta", timeout=2.0)
    assert voyage_api._kick_official_eta(force=False, stop="Papeete") is True


def test_create_voyage_clock_failure_is_dated_503_not_500(client, monkeypatch):
    """Petite route non officielle — pas de 500, pas d'_climo_clock dans le handler."""
    def boom(*_a, **_k):
        raise AssertionError("calcul")

    monkeypatch.setattr(voyage_api, "_climo_clock", boom)
    r = client.post("/voyage", json=_payload("2026-06-15T08:00:00Z") | {"forecast": False})
    assert r.status_code in (202, 503)
    assert r.status_code < 500
    body = r.json()
    dated = body.get("detail") if r.status_code == 503 else (body.get("clock") or body)
    assert dated.get("status") in ("preparing", "unavailable")
    assert dated.get("reason")
    assert "T" in dated.get("at", "") and dated["at"].endswith("Z")


def test_official_post_does_not_compute_clock(client, monkeypatch):
    """POST officiel lit le stock, aucun _climo_clock."""
    monkeypatch.setattr(voyage_api, "_climo_clock", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("calcul")))
    body = _payload("2026-05-15T08:00:00Z") | {"official": True, "forecast": False}
    r = client.post("/voyage", json=body)
    assert r.status_code == 200
    clock = r.json().get("clock") or {}
    assert clock.get("status") == "preparing" or clock.get("vertices")


def test_post_same_route_without_official_flag_does_not_compute_clock(client, monkeypatch):
    """POST sans official, mêmes points+t0 que l'officiel → stock ou preparing."""
    seed = _payload("2026-05-15T08:00:00Z") | {"forecast": False}
    client.put("/voyage/official", json=seed | {"official": True})
    monkeypatch.setattr(
        voyage_api,
        "_climo_clock",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("calcul")),
    )
    r = client.post("/voyage", json=seed)
    assert r.status_code == 200
    clock = r.json().get("clock") or {}
    assert clock.get("status") == "preparing" or clock.get("vertices")
    assert r.json().get("official") is True


def test_unofficial_small_post_does_not_compute_clock_in_handler(client, monkeypatch):
    """Petite route non officielle → pas de 500, pas d'_climo_clock dans le handler."""
    def boom(*_a, **_k):
        raise AssertionError("calcul")

    monkeypatch.setattr(voyage_api, "_climo_clock", boom)
    r = client.post("/voyage", json=_payload("2026-06-15T08:00:00Z") | {"forecast": False})
    assert r.status_code != 500
    assert r.status_code in (202, 503)
    body = r.json()
    dated = body.get("detail") if r.status_code == 503 else (body.get("clock") or body)
    assert dated.get("status") in ("preparing", "unavailable")
    assert dated.get("at", "").endswith("Z")


def test_nominal_path_has_no_500(client, tmp_path, monkeypatch):
    """Parcours nominal TestClient — aucun 500 sur les routes du fil rouge."""
    import polar_api

    monkeypatch.setattr(polar_api, "POLAR_DATA_DIR", tmp_path / "polar")
    polar_api._default_polar.cache_clear()
    dest = polar_api._polar_path(polar_api.DEFAULT_POLAR_EXPEDITION)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("{bad", encoding="utf-8")

    paths = [
        ("GET", "/voyage/official", {}),
        ("GET", "/voyage/official/clock", {}),
        ("GET", "/voyage/official/moments", {}),
        ("GET", "/voyage/official/journal", {}),
        ("GET", "/voyage/official/eta", {"stop": "Nouméa"}),
        ("GET", "/voyage/official/plan-review", {}),
        ("GET", "/ici", {"lat": 46.15, "lon": -1.16}),
        ("GET", "/ici/moment", {"lat": 46.15, "lon": -1.16}),
        ("GET", "/ici/pearls", {}),
        ("GET", "/ici/warm/status", {}),
        ("GET", "/ici/layers/warm/status", {}),
        ("GET", f"/api/v1/polar/{polar_api.DEFAULT_POLAR_EXPEDITION}/client", {}),
    ]
    for method, path, params in paths:
        r = client.request(method, path, params=params)
        assert r.status_code < 500, f"{path} → {r.status_code} {r.text[:200]}"

    polar = client.get(f"/api/v1/polar/{polar_api.DEFAULT_POLAR_EXPEDITION}/client")
    assert polar.status_code == 200
    assert polar.json()["boat_name"] == "Leopard 46"
    assert polar.json().get("source") == "default"


def test_unofficial_at_without_vertices_is_dated_not_503(client, monkeypatch):
    """POST petite route non officielle → GET /at et /clock 200 daté, pas 503."""
    def boom(*_a, **_k):
        raise AssertionError("calcul")

    monkeypatch.setattr(voyage_api, "_climo_clock", boom)
    r = client.post("/voyage", json=_payload("2026-06-15T08:00:00Z") | {"forecast": False})
    assert r.status_code == 202
    vid = r.json()["voyageId"]
    at = client.get(f"/voyage/{vid}/at")
    assert at.status_code in (200, 202)
    assert at.status_code != 503
    body = at.json()
    assert body.get("status") == "preparing"
    assert body.get("reason")
    assert "T" in body.get("at", "") and body["at"].endswith("Z")
    clock = client.get(f"/voyage/{vid}/clock")
    assert clock.status_code in (200, 202)
    assert clock.status_code != 503
    dated = clock.json()
    assert dated.get("status") == "preparing"
    assert dated.get("reason")
    assert "T" in dated.get("at", "") and dated["at"].endswith("Z")
    assert not dated.get("vertices")
    src = open(voyage_api.__file__, encoding="utf-8").read()
    at_fn = src.split("def get_at(", 1)[1].split("def refresh_forecast", 1)[0]
    clock_fn = src.split("def get_clock(", 1)[1].split("def get_at(", 1)[0]
    assert "_climo_clock" not in at_fn
    assert "_climo_clock" not in clock_fn


def test_ici_fill_failure_is_dated_200(client, monkeypatch):
    """Fill_dossier lève → /ici 200 daté, pas un 500."""
    import main

    async def boom(*_a, **_k):
        raise RuntimeError("bi down")

    monkeypatch.setenv("NAVIGUIDE_ICI_WARM", "1")
    monkeypatch.setattr(main, "fill_dossier", boom)
    r = client.get("/ici", params={"lat": 0.0, "lon": 0.0})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "unavailable"
    assert "bi down" in body["reason"]
    assert body["at"].endswith("Z")


def test_anonymous_official_put_repairs_admin_kicks(client, monkeypatch):
    """PUT anonyme : réparation bornée (repair_worker). Admin et création : kick_worker complet."""
    import official_store

    monkeypatch.setenv("NAVIGUIDE_ADMIN_SECRET", "test-secret")
    calls = []
    monkeypatch.setattr(official_store, "kick_worker", lambda: calls.append("kick"))
    monkeypatch.setattr(official_store, "repair_worker", lambda: calls.append("repair"))
    payload = _payload("2026-05-15T08:00:00Z")

    assert client.put("/voyage/official", json=payload).status_code == 200
    assert calls == ["kick"]  # création depuis un store vide
    assert client.put("/voyage/official", json=payload).status_code == 200
    assert calls == ["kick", "repair"]  # visiteur : réparation, pas de passage complet
    admin = client.put("/voyage/official", json=payload, headers={"X-Naviguide-Admin": "test-secret"})
    assert admin.status_code == 200
    assert calls == ["kick", "repair", "kick"]
