"""ETA p10/p50/p90, faux serveur HTTP Ensemble, cache 6 h."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import httpx
import pytest

from hindcast import bind_http, block_network, reset_hooks, unblock_network
from pearl_store import kv_get

import ensemble_eta
from ensemble_eta import (
    CACHE_NS,
    CACHE_TTL_S,
    ENSEMBLE_MODELS,
    ETA_MAX_SPAN_DAYS,
    ETA_MIN_KN,
    FORECAST_DAYS,
    MAX_PROBES_PER_LEG,
    REASON_UNAVAILABLE,
    arrival_quantiles,
    bound_eta_quantiles,
    REASON_QUOTA,
    REASON_QUOTA_LABEL,
    compute_eta,
    compute_next_retry,
    empty_eta,
    explain_eta_reason,
    empirical_quantile,
    eta_retry_due,
    fetch_point_members,
    implied_speed_kn,
    next_official_stop,
    parse_members,
    peek_official_eta,
    preheat_official_eta,
    sample_leg_points,
    tighten_eta_arrivals,
    tighten_eta_payload,
)

NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
LAT, LON = 46.15, -1.16

C4_POLAR = {
    "twa_rows": [40, 60, 90, 120, 150, 180],
    "tws_cols": [8, 12, 16, 20],
    "matrix": [
        [5.0, 6.5, 7.5, 8.0],
        [6.0, 7.5, 8.5, 9.0],
        [7.0, 8.5, 9.5, 10.0],
        [6.5, 8.0, 9.0, 10.0],
        [5.5, 7.0, 8.0, 9.0],
        [4.5, 6.0, 7.0, 8.0],
    ],
}


@pytest.fixture(autouse=True)
def _hooks():
    reset_hooks()
    saved_url = ensemble_eta.ENSEMBLE_URL
    ensemble_eta._reset_fetch_note()
    yield
    ensemble_eta.ENSEMBLE_URL = saved_url
    reset_hooks()
    unblock_network()
    ensemble_eta._reset_fetch_note()


def _hours(n: int = 48) -> list[str]:
    return [(NOW + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(n)]


def _ensemble_json(times: list[str], speeds: list[float], direction: float = 0.0) -> dict:
    hourly = {"time": times}
    for i, kn in enumerate(speeds, start=1):
        hourly[f"wind_speed_10m_member{i:02d}"] = [kn] * len(times)
        hourly[f"wind_direction_10m_member{i:02d}"] = [direction] * len(times)
    return {"hourly": hourly}


class _EnsembleHandler(BaseHTTPRequestHandler):
    payload = {"hourly": {"time": []}}
    hits = 0
    fail = False

    def do_GET(self):  # noqa: N802
        type(self).hits += 1
        if self.fail:
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b"down")
            return
        body = json.dumps(self.payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a):
        return


def _start_server(payload: dict, *, fail: bool = False):
    _EnsembleHandler.payload = payload
    _EnsembleHandler.hits = 0
    _EnsembleHandler.fail = fail
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EnsembleHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _bind_server(server: ThreadingHTTPServer):
    host, port = server.server_address
    origin = f"http://{host}:{port}"

    def factory():
        return httpx.Client(timeout=5.0)

    bind_http(factory)
    ensemble_eta.ENSEMBLE_URL = origin + "/v1/ensemble"
    return origin


def _leg():
    points = [
        {"lat": 46.15, "lon": -1.16, "cumNm": 0, "filmCum": 0, "jump": False, "nonMaritime": False},
        {"lat": 46.15, "lon": -2.16, "cumNm": 30, "filmCum": 30, "jump": False, "nonMaritime": False},
    ]
    marks = [{"name": "Fort-de-France (Martinique)", "nm": 30, "filmNm": 30, "lat": 46.15, "lon": -2.16, "index": 1}]
    sample = {"lat": 46.15, "lon": -1.16, "sailNm": 0, "filmNm": 0}
    return points, marks, sample


def test_quantiles_identical_and_dispersed():
    t0 = NOW
    same = [t0 + timedelta(hours=48)] * 30
    p10, p50, p90 = arrival_quantiles(same)
    assert p10 == p50 == p90
    assert p10 == same[0]
    spread = [t0 + timedelta(hours=h) for h in (20, 24, 28, 32, 36, 40, 48, 56, 64, 72)]
    a, b, c = arrival_quantiles(spread)
    assert a < b < c
    assert empirical_quantile([1.0, 1.0, 1.0], 0.1) == 1.0


def test_parse_members_control_and_prefixed():
    times = _hours(3)
    payload = {
        "hourly": {
            "time": times,
            "wind_speed_10m": [10.0, 10.0, 10.0],
            "wind_direction_10m": [0.0, 0.0, 0.0],
            "gfs_seamless_wind_speed_10m_member01": [12.0, 12.0, 12.0],
            "gfs_seamless_wind_direction_10m_member01": [90.0, 90.0, 90.0],
        }
    }
    members = parse_members(payload)
    assert "control" in members
    assert any(k.endswith("member01") for k in members)
    assert members["control"][0]["speedKnots"] == 10.0


def test_thirty_identical_members_p10_eq_p90():
    times = _hours(72)
    payload = _ensemble_json(times, [12.0] * 30, direction=0.0)
    server = _start_server(payload)
    try:
        _bind_server(server)
        points, marks, sample = _leg()
        out = compute_eta(
            points=points, marks=marks, stop="Fort-de-France",
            now=NOW, polar_raw=C4_POLAR, sample=sample,
        )
        assert out["members"] == 30
        assert out["p10"] and out["p50"] and out["p90"]
        assert out["p10"] == out["p50"] == out["p90"]
        assert out["source"] == "open-meteo-ensemble"
    finally:
        server.shutdown()


def test_dispersed_members_p10_lt_p50_lt_p90():
    times = _hours(96)
    speeds = [8.0] * 10 + [12.0] * 10 + [20.0] * 10
    payload = _ensemble_json(times, speeds, direction=0.0)
    server = _start_server(payload)
    try:
        _bind_server(server)
        points, marks, sample = _leg()
        out = compute_eta(
            points=points, marks=marks, stop="Fort-de-France",
            now=NOW, polar_raw=C4_POLAR, sample=sample,
        )
        assert out["members"] == 30
        assert out["p10"] < out["p50"] < out["p90"]
    finally:
        server.shutdown()


def test_api_down_members_zero():
    server = _start_server({"hourly": {"time": []}}, fail=True)
    try:
        _bind_server(server)
        points, marks, sample = _leg()
        out = compute_eta(
            points=points, marks=marks, stop="Fort-de-France",
            now=NOW, polar_raw=C4_POLAR, sample=sample,
        )
        assert out["members"] == 0
        assert out["p10"] is None and out["p50"] is None and out["p90"] is None
        assert out["source"] is None
        assert out["reason"] == REASON_UNAVAILABLE
        assert out["lastAttempt"]
        assert out["nextRetry"]
        assert empty_eta(NOW)["members"] == 0
    finally:
        server.shutdown()


def test_cache_six_hours_second_call_without_network():
    times = _hours(24)
    payload = _ensemble_json(times, [12.0] * 5, direction=0.0)
    server = _start_server(payload)
    try:
        _bind_server(server)
        first = fetch_point_members(LAT, LON)
        assert first
        hits = _EnsembleHandler.hits
        assert hits >= 1
        block_network()
        second = fetch_point_members(LAT, LON)
        assert len(second) == len(first)
        assert _EnsembleHandler.hits == hits
        assert CACHE_TTL_S == 6 * 3600
        hit = kv_get(CACHE_NS, ensemble_eta._cache_key(LAT, LON), max_age_s=CACHE_TTL_S)
        assert hit and hit["value"]["members"]
    finally:
        unblock_network()
        server.shutdown()


def test_sample_leg_points_step_at_most_60nm():
    points = [
        {"lat": 0.0, "lon": 0.0, "cumNm": 0},
        {"lat": 0.0, "lon": 0.1, "cumNm": 20},
        {"lat": 0.0, "lon": 2.0, "cumNm": 140},
        {"lat": 0.0, "lon": 2.1, "cumNm": 150},
    ]
    sampled = sample_leg_points(points, 60.0)
    assert sampled[0]["cumNm"] == 0
    assert sampled[-1]["cumNm"] == 150
    gaps = [sampled[i + 1]["cumNm"] - sampled[i]["cumNm"] for i in range(len(sampled) - 1)]
    assert all(g <= 60.0 + 1e-6 for g in gaps)
    assert ENSEMBLE_MODELS == "gfs_seamless,ecmwf_ifs025"
    assert FORECAST_DAYS == 15


def test_compute_eta_drops_zero_wind_member():
    times = _hours(96)
    speeds = [12.0] * 29 + [0.0]
    payload = _ensemble_json(times, speeds, direction=0.0)
    server = _start_server(payload)
    try:
        _bind_server(server)
        points, marks, sample = _leg()
        out = compute_eta(
            points=points, marks=marks, stop="Fort-de-France",
            now=NOW, polar_raw=C4_POLAR, sample=sample,
        )
        assert out["members"] >= 1
        assert all(float(k) >= ETA_MIN_KN for k in (out.get("memberKnots") or []))
        assert 0.0 not in (out.get("memberKnots") or [])
    finally:
        server.shutdown()


def test_zero_kn_member_is_dropped_and_span_is_days():
    now = NOW
    remaining = 9151.0
    healthy = [now + timedelta(days=47.7 + (i - 40) * 0.05) for i in range(80)]
    dead = now + timedelta(days=remaining / 0.5 / 24)
    healthy[0] = dead
    assert implied_speed_kn(remaining, now, dead) < ETA_MIN_KN
    kept = tighten_eta_arrivals(healthy, remaining_nm=remaining, now=now)
    assert dead not in kept
    assert all(implied_speed_kn(remaining, now, a) >= ETA_MIN_KN for a in kept)
    p10, p50, p90 = arrival_quantiles(kept)
    p10, p50, p90 = bound_eta_quantiles(p10, p50, p90)
    span = (p90 - p10).total_seconds() / 86400.0
    assert span <= ETA_MAX_SPAN_DAYS + 1e-6
    exploded = {
        "members": 80,
        "p10": (now + timedelta(days=53)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "p50": (now + timedelta(days=55)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "p90": (now + timedelta(days=262)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "memberKnots": [8.0, 8.1, 0.0],
        "source": "open-meteo-ensemble",
    }
    tight = tighten_eta_payload(exploded, now)
    assert tight["members"] == 80
    t10, t90 = datetime.fromisoformat(tight["p10"].replace("Z", "+00:00")), datetime.fromisoformat(tight["p90"].replace("Z", "+00:00"))
    assert (t90 - t10).total_seconds() / 86400.0 <= ETA_MAX_SPAN_DAYS + 1e-6
    assert 0.0 not in (tight.get("memberKnots") or [])


def _official_noumea_dzaoudzi():
    """Fixture officielle : Nouméa déjà passé, Dzaoudzi à ~9 150 nm (jambe réelle)."""
    t0 = "2026-05-15T08:00:00Z"
    now_iso = "2026-09-22T12:00:00Z"
    remaining = 9151.0
    points = [
        {"lat": -22.27, "lon": 166.44, "cumNm": 0, "filmCum": 0, "jump": False, "nonMaritime": False},
        {"lat": -12.78, "lon": 45.23, "cumNm": remaining, "filmCum": remaining, "jump": False, "nonMaritime": False},
    ]
    marks = [
        {
            "name": "Nouméa (Nouvelle-Calédonie)",
            "nm": 0, "filmNm": 0, "lat": -22.27, "lon": 166.44,
            "iso": "2026-09-17T22:48:00Z", "index": 0,
        },
        {
            "name": "Dzaoudzi (Mayotte)",
            "nm": remaining, "filmNm": remaining, "lat": -12.78, "lon": 45.23,
            "iso": "2026-11-15T00:00:00Z", "index": 1,
        },
    ]
    return {
        "points": points,
        "marks": marks,
        "t0": t0,
        "startAt": "saint-maur",
        "expedition_id": "berry-mappemonde-2026",
        "clock": {
            "t0": t0,
            "marks": marks,
            "vertices": [
                {"tHours": 0, "sailNm": 0, "filmNm": 0, "lat": -22.27, "lon": 166.44, "iso": t0},
                {"tHours": 3124, "sailNm": 0, "filmNm": 0, "lat": -22.27, "lon": 166.44, "iso": now_iso},
            ],
        },
    }


def _fixture_members(n: int = 12, kn: float = 10.0) -> dict:
    times = _hours(24)
    out = {}
    for i in range(1, n + 1):
        speed = kn + (i - n / 2) * 0.35
        out[f"member{i:02d}"] = [
            {"t": t, "speedKnots": speed, "dirFromDeg": 90.0} for t in times
        ]
    return out


def test_next_official_stop_is_dzaoudzi_after_noumea():
    voy = _official_noumea_dzaoudzi()
    assert "Dzaoudzi" in next_official_stop(voy, NOW)
    later = datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert next_official_stop(voy, later) == ""


def test_preheat_official_noumea_dzaoudzi_members_no_network(monkeypatch):
    """Préchauffage sur fixture officielle, sans HTTP, fenêtre de quelques jours."""
    voy = _official_noumea_dzaoudzi()
    members = _fixture_members()

    def fake_integrate(points, stop_name, now, polar_raw, wind_fn):
        assert "Dzaoudzi" in stop_name
        pack = wind_fn(-22.0, 165.0, now)
        kn = float((pack or {}).get("speedKnots") or 10.0)
        days = 47.7 + (10.0 - kn) * 0.35
        return NOW + timedelta(days=days)

    monkeypatch.setattr(ensemble_eta, "fetch_point_members", lambda *_a, **_k: members)
    monkeypatch.setattr(ensemble_eta, "_integrate_member", fake_integrate)
    block_network()
    try:
        out = preheat_official_eta(voy, NOW, polar_raw=C4_POLAR)
    finally:
        unblock_network()
    assert out["members"] > 0
    assert out["p10"] and out["p50"] and out["p90"]
    t10 = datetime.fromisoformat(out["p10"].replace("Z", "+00:00"))
    t90 = datetime.fromisoformat(out["p90"].replace("Z", "+00:00"))
    span = (t90 - t10).total_seconds() / 86400.0
    assert span <= ETA_MAX_SPAN_DAYS + 1e-6
    assert all(float(k) >= ETA_MIN_KN for k in (out.get("memberKnots") or []))


def test_preheat_without_members_invents_nothing(monkeypatch):
    monkeypatch.setattr(ensemble_eta, "fetch_point_members", lambda *_a, **_k: {})
    block_network()
    try:
        out = preheat_official_eta(_official_noumea_dzaoudzi(), NOW, polar_raw=C4_POLAR)
    finally:
        unblock_network()
    assert out["members"] == 0
    assert out["p10"] is None and out["p90"] is None
    assert out.get("reason")
    assert not out.get("p10") and not out.get("p50")


def test_kick_official_eta_does_not_block(monkeypatch):
    import time
    import voyage_api
    from weather_pipeline import get_pipeline

    started = threading.Event()
    release = threading.Event()

    def fake_preheat(*_a, **_k):
        started.set()
        release.wait(2)
        return {"members": 12, "p10": "2026-11-13T00:00:00Z", "p90": "2026-11-16T00:00:00Z"}

    monkeypatch.setenv("NAVIGUIDE_ETA_PREHEAT", "1")
    monkeypatch.setattr(voyage_api, "load_voyage", lambda *_a, **_k: _official_noumea_dzaoudzi())
    monkeypatch.setattr(ensemble_eta, "preheat_official_eta", fake_preheat)
    get_pipeline().clear()
    t0 = time.monotonic()
    assert voyage_api._kick_official_eta() is True
    assert time.monotonic() - t0 < 0.5
    assert started.wait(1)
    assert voyage_api._kick_official_eta() is False
    release.set()


def test_startup_and_put_kick_official_eta():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    main_src = (root / "main.py").read_text()
    api_src = (root / "voyage_api.py").read_text()
    assert "_kick_official_eta" in main_src
    assert "startup_official_voyage" in main_src
    assert "seed_official_voyage" in api_src
    assert "official_store.kick_worker" in api_src
    assert "_maybe_daily_hindcast" in api_src
    assert "kick_official_warmups" in api_src


def test_sample_leg_points_capped_at_12_keeps_ends():
    points = [
        {"lat": 4.9, "lon": -52.3, "cumNm": 0},
        {"lat": -17.5, "lon": -149.5, "cumNm": 7504},
    ]
    sampled = sample_leg_points(points, 60.0)
    assert sampled[0]["cumNm"] == 0
    assert sampled[-1]["cumNm"] == 7504
    assert len(sampled) == MAX_PROBES_PER_LEG
    assert len(sampled) <= 12
    assert MAX_PROBES_PER_LEG == 12


def test_compute_eta_caps_fetches_on_long_leg(monkeypatch):
    calls = []

    def fake_fetch(lat, lon):
        calls.append((lat, lon))
        return _fixture_members(4, kn=10.0)

    def fake_integrate(_points, stop_name, now, polar_raw, wind_fn):
        pack = wind_fn(-10.0, -100.0, now)
        kn = float((pack or {}).get("speedKnots") or 10.0)
        return NOW + timedelta(days=20 + (10.0 - kn) * 0.2)

    monkeypatch.setattr(ensemble_eta, "fetch_point_members", fake_fetch)
    monkeypatch.setattr(ensemble_eta, "_integrate_member", fake_integrate)
    points = [
        {"lat": 4.9, "lon": -52.3, "cumNm": 0, "filmCum": 0, "jump": False, "nonMaritime": False},
        {"lat": -17.5, "lon": -149.5, "cumNm": 4200, "filmCum": 4200, "jump": False, "nonMaritime": False},
    ]
    marks = [{"name": "Papeete", "nm": 4200, "filmNm": 4200, "lat": -17.5, "lon": -149.5, "index": 1}]
    sample = {"lat": 4.9, "lon": -52.3, "sailNm": 0, "filmNm": 0}
    out = compute_eta(
        points=points, marks=marks, stop="Papeete",
        now=NOW, polar_raw=C4_POLAR, sample=sample,
    )
    assert len(calls) <= 12
    assert out["members"] > 0
    assert out["p10"] and out["p90"]
    t10 = datetime.fromisoformat(out["p10"].replace("Z", "+00:00"))
    t90 = datetime.fromisoformat(out["p90"].replace("Z", "+00:00"))
    assert (t90 - t10).total_seconds() / 86400.0 <= ETA_MAX_SPAN_DAYS + 1e-6


def test_compute_next_retry_quota_is_tomorrow():
    nxt = compute_next_retry(
        NOW, 0, "Daily API request limit exceeded. Please try again tomorrow.",
    )
    assert nxt.date() == (NOW + timedelta(days=1)).date()
    assert nxt.hour == 0 and nxt.minute == 15
    stepped = compute_next_retry(NOW, 0, None)
    assert stepped == NOW + timedelta(seconds=30)
    later = compute_next_retry(NOW, 5, None)
    assert later == NOW + timedelta(seconds=900)


def test_eta_retry_due_respects_backoff():
    assert eta_retry_due({"members": 0}, NOW) is True
    assert eta_retry_due({"members": 12, "p10": "x", "p90": "y"}, NOW) is False
    future = (NOW + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert eta_retry_due({"members": 0, "nextRetry": future}, NOW) is False
    past = (NOW - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert eta_retry_due({"members": 0, "nextRetry": past}, NOW) is True


def test_peek_after_failed_compute_keeps_reason(monkeypatch):
    monkeypatch.setattr(ensemble_eta, "fetch_point_members", lambda *_a, **_k: {})
    points, marks, sample = _leg()
    voy = {"points": points, "marks": marks, "clock": None}
    out = compute_eta(
        points=points, marks=marks, stop="Fort-de-France",
        now=NOW, polar_raw=C4_POLAR, sample=sample,
    )
    assert out["members"] == 0
    assert out["reason"] == REASON_UNAVAILABLE
    peeked = peek_official_eta(voy, "Fort-de-France", NOW)
    assert peeked["members"] == 0
    assert peeked["reason"] == REASON_UNAVAILABLE
    assert peeked["lastAttempt"]
    assert peeked["nextRetry"]
    assert peeked["p10"] is None and peeked["p90"] is None


def test_rg17_429_writes_quota_reason_and_does_not_retry(monkeypatch):
    import pearl_store
    from hindcast import om_quota_blocked

    pearl_store.reset()
    reset_hooks()
    hits = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        return httpx.Response(
            429,
            text="Daily API request limit exceeded. Please try again tomorrow.",
        )

    bind_http(lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    points, marks, sample = _leg()
    out = compute_eta(
        points=points, marks=marks, stop="Fort-de-France",
        now=NOW, polar_raw=C4_POLAR, sample=sample,
    )
    assert out["members"] == 0
    assert out["p10"] is None and out["p90"] is None
    assert out["reason"] == REASON_QUOTA
    assert explain_eta_reason(out) == REASON_QUOTA_LABEL
    nxt = datetime.fromisoformat(out["nextRetry"].replace("Z", "+00:00"))
    assert nxt.date() == (NOW + timedelta(days=1)).date()
    assert om_quota_blocked()
    assert hits["n"] == 1
    out2 = compute_eta(
        points=points, marks=marks, stop="Fort-de-France",
        now=NOW, polar_raw=C4_POLAR, sample=sample,
    )
    assert hits["n"] == 1
    assert out2["members"] == 0
    assert out2["nextRetry"]
    pearl_store.reset()
    reset_hooks()
