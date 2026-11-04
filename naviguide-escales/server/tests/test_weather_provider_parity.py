"""Parité : drapeau éteint (ancien chemin) et drapeau allumé servent les mêmes valeurs."""

import climatology_atlas
from weather_pipeline import get_async_weather_queue, get_pipeline, route_snapshot

WAVE_OPENMETEO = {
    "kind": "forecast",
    "source": "openmeteo-gfs-wave",
    "hs": 1.1,
    "dirDeg": 270.0,
    "periodS": 6.5,
    "time": "2026-09-16T09:00",
}

WAVE_COPERNICUS = {
    "latitude": 46.15,
    "longitude": -1.16,
    "significant_wave_height_m": 2.4,
    "mean_wave_period": 8.5,
    "mean_wave_direction": 310.0,
    "source": "copernicus-marine",
}


def _serve(monkeypatch, flag, provider, fixture, lat=46.15, lon=-1.16):
    monkeypatch.setenv("NAVIGUIDE_WEATHER_PIPELINE", flag)
    get_pipeline().clear()
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return dict(fixture)

    body = route_snapshot(provider, lat, lon, loader)
    if body.get("status") != "ready":
        get_pipeline().wait_ready(provider, lat, lon, timeout=2)
        body = route_snapshot(provider, lat, lon, loader)
    assert body["status"] == "ready", body
    for key, value in fixture.items():
        assert body[key] == value
    assert calls["n"] == 1
    if flag not in {"0", "off", "false", "no"}:
        queued = get_async_weather_queue().wait_layer(provider, lat, lon, timeout=2)
        assert queued["status"] == "ready"
        for key, value in fixture.items():
            assert queued[key] == value
    return {key: body[key] for key in fixture}


def test_openmeteo_wave_parity(monkeypatch):
    off = _serve(monkeypatch, "0", "openmeteo-gfs-wave", WAVE_OPENMETEO)
    on = _serve(monkeypatch, "1", "openmeteo-gfs-wave", WAVE_OPENMETEO)
    assert off == on == WAVE_OPENMETEO
    assert get_async_weather_queue().cached_status("openmeteo-gfs-wave", 46.15, -1.16) == "ready"


CURRENT_RTOFS = {
    "current": {
        "kind": "forecast",
        "source": "noaa-rtofs",
        "speedKnots": 0.58,
        "dirToDeg": 247.0,
        "issued": "2026-09-16T00:00:00Z",
    },
    "current_reason": None,
}

CURRENT_COPERNICUS = {
    "latitude": 46.15,
    "longitude": -1.16,
    "u_component": 0.12,
    "v_component": 0.0,
    "speed_ms": 0.12,
    "speed_knots": 0.23,
    "direction_deg": 90.0,
    "source": "copernicus-marine",
}


def test_copernicus_wave_parity(monkeypatch):
    off = _serve(monkeypatch, "0", "wave", WAVE_COPERNICUS)
    on = _serve(monkeypatch, "1", "wave", WAVE_COPERNICUS)
    assert off == on == WAVE_COPERNICUS
    assert get_async_weather_queue().cached_status("wave", 46.15, -1.16) == "ready"


def test_rtofs_current_parity(monkeypatch):
    off = _serve(monkeypatch, "0", "noaa-rtofs", CURRENT_RTOFS)
    on = _serve(monkeypatch, "1", "noaa-rtofs", CURRENT_RTOFS)
    assert off == on == CURRENT_RTOFS
    assert off["current"]["speedKnots"] == 0.58
    assert get_async_weather_queue().cached_status("noaa-rtofs", 46.15, -1.16) == "ready"


def test_copernicus_current_parity(monkeypatch):
    off = _serve(monkeypatch, "0", "current", CURRENT_COPERNICUS)
    on = _serve(monkeypatch, "1", "current", CURRENT_COPERNICUS)
    assert off == on == CURRENT_COPERNICUS
    assert get_async_weather_queue().cached_status("current", 46.15, -1.16) == "ready"


CLIMO_POINT = {
    "kind": "climatology",
    "month": 6,
    "period": "1980-2020",
    "wave": {"hs_p50_m": 1.4, "hs_p90_m": 2.8},
    "current": {"speed_knots": 0.4, "direction_to_deg": 270},
    "cyclone": {"nearby": 0, "tracks_in_month": 4},
}


def _climo_point(monkeypatch, flag):
    monkeypatch.setenv("NAVIGUIDE_WEATHER_PIPELINE", flag)
    climatology_atlas.reset_atlas_cache()
    get_pipeline().clear()
    seen = []

    def fake(url, params, client=None):
        seen.append(url)
        return dict(CLIMO_POINT)

    monkeypatch.setattr(climatology_atlas, "_get_json", fake)
    payload = climatology_atlas.fetch_atlas_point(46.15, -1.16, 6)
    assert payload == CLIMO_POINT
    assert seen == [f"{climatology_atlas.bi_base()}/climatology/point"]
    return payload, seen[0]


WIND_COPERNICUS = {
    "latitude": 46.15,
    "longitude": -1.16,
    "wind_speed_knots": 12.0,
    "wind_direction": 280.0,
    "source": "copernicus-marine",
}


WIND_OPENMETEO = {
    "kind": "forecast",
    "source": "openmeteo-gfs",
    "speedKnots": 12.4,
    "dirFromDeg": 280.0,
    "time": "2026-09-16T09:00",
}


def test_openmeteo_wind_parity(monkeypatch):
    off = _serve(monkeypatch, "0", "openmeteo-gfs", WIND_OPENMETEO)
    on = _serve(monkeypatch, "1", "openmeteo-gfs", WIND_OPENMETEO)
    assert off == on == WIND_OPENMETEO
    assert off["speedKnots"] == 12.4
    assert get_async_weather_queue().cached_status("openmeteo-gfs", 46.15, -1.16) == "ready"


def test_copernicus_wind_parity(monkeypatch):
    off = _serve(monkeypatch, "0", "wind", WIND_COPERNICUS)
    on = _serve(monkeypatch, "1", "wind", WIND_COPERNICUS)
    assert off == on == WIND_COPERNICUS
    assert off["wind_speed_knots"] == 12.0
    assert get_async_weather_queue().cached_status("wind", 46.15, -1.16) == "ready"


def test_climatology_point_parity_keeps_public_bi_api(monkeypatch):
    off, url_off = _climo_point(monkeypatch, "0")
    on, url_on = _climo_point(monkeypatch, "1")
    assert off == on == CLIMO_POINT
    assert url_off == url_on
    assert url_on.endswith("/climatology/point")
    assert url_on == f"{climatology_atlas.bi_base()}/climatology/point"
    assert get_async_weather_queue().cached_status("bi-climatology-m6", 46.15, -1.16) == "ready"


def test_bi_outage_is_not_cached(monkeypatch):
    """Une panne de BI ne reste pas en cache : après la pause, l'API est vraiment rappelée."""
    monkeypatch.setenv("NAVIGUIDE_WEATHER_PIPELINE", "on")
    climatology_atlas.reset_atlas_cache()
    get_pipeline().clear()
    get_async_weather_queue().clear()
    calls = []

    def down(url, params, client=None):
        calls.append(url)
        raise RuntimeError("bi 503")

    monkeypatch.setattr(climatology_atlas, "_get_json", down)
    assert climatology_atlas.fetch_atlas_point(46.15, -1.16, 6) is None
    assert len(calls) == 1
    assert get_async_weather_queue().cached_status("bi-climatology-m6", 46.15, -1.16) != "unavailable"
    # Pendant la pause : aucun appel.
    assert climatology_atlas.fetch_atlas_point(46.15, -1.16, 6) is None
    assert len(calls) == 1

    climatology_atlas.reset_atlas_cache()  # fin de la pause
    def up(url, params, client=None):
        calls.append(url)
        return dict(CLIMO_POINT)

    monkeypatch.setattr(climatology_atlas, "_get_json", up)
    assert climatology_atlas.fetch_atlas_point(46.15, -1.16, 6) == CLIMO_POINT
    assert len(calls) == 2
    assert get_async_weather_queue().cached_status("bi-climatology-m6", 46.15, -1.16) == "ready"


def test_slow_answer_pauses_once_not_from_cache(monkeypatch):
    """Une case lente met l'atlas en pause une fois ; relue en cache, elle ne relance pas la pause."""
    import time as _time
    monkeypatch.setenv("NAVIGUIDE_WEATHER_PIPELINE", "on")
    climatology_atlas.reset_atlas_cache()
    get_pipeline().clear()
    get_async_weather_queue().clear()
    monkeypatch.setattr(climatology_atlas, "SLOW_S", 0.05)
    monkeypatch.setattr(climatology_atlas, "DEAD_S", 0.2)
    calls = []

    def slow(url, params, client=None):
        calls.append(url)
        _time.sleep(0.1)
        return dict(CLIMO_POINT)

    monkeypatch.setattr(climatology_atlas, "_get_json", slow)
    assert climatology_atlas.fetch_atlas_point(46.15, -1.16, 6) == CLIMO_POINT
    assert climatology_atlas.atlas_is_dead()
    _time.sleep(0.25)
    assert not climatology_atlas.atlas_is_dead()
    # Relecture de la même case : servie par le cache, sans nouvel appel ni nouvelle pause.
    assert climatology_atlas.fetch_atlas_point(46.15, -1.16, 6) == CLIMO_POINT
    assert len(calls) == 1
    assert not climatology_atlas.atlas_is_dead()


def test_bi_answers_after_the_wait_then_recovers(monkeypatch):
    """BI répond après la fin de l'attente (travail encore en cours) : rien ne reste collé ensuite."""
    import time as _time
    monkeypatch.setenv("NAVIGUIDE_WEATHER_PIPELINE", "on")
    climatology_atlas.reset_atlas_cache()
    get_pipeline().clear()
    get_async_weather_queue().clear()
    monkeypatch.setattr(climatology_atlas, "TIMEOUT_S", 0.1)
    monkeypatch.setattr(climatology_atlas, "DEAD_S", 0.3)
    state = {"up": False, "delay": 1.0}

    def bi(url, params, client=None):
        _time.sleep(state["delay"])
        if not state["up"]:
            raise RuntimeError("bi 503")
        return dict(CLIMO_POINT)

    monkeypatch.setattr(climatology_atlas, "_get_json", bi)
    assert climatology_atlas.fetch_atlas_point(46.15, -1.16, 6) is None
    _time.sleep(1.2)  # le travail finit en échec après l'attente
    state.update(up=True, delay=0.0)
    _time.sleep(0.35)
    assert not climatology_atlas.atlas_is_dead()
    assert climatology_atlas.fetch_atlas_point(46.15, -1.16, 6) == CLIMO_POINT
