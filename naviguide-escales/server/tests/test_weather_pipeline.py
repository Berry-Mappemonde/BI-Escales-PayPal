import threading
import time
from datetime import datetime, timedelta, timezone

from hindcast import MS_TO_KN, uv_to_current_to, uv_to_wind_from
from saildocs import knots_from_uv, last_ready_cycle, to_iso
from voyage_clock import MS_TO_KN as CLOCK_MS_TO_KN
from weather_pipeline import (
    AsyncWeatherQueue,
    WeatherPipeline,
    cache_key,
    forecast_cycle,
    layer_cache_key,
    weather_cell,
    weather_pipeline_enabled,
)

# 1 kn = 1852 m/h exactement → 1 m/s = 3600/1852 kn.
EXACT_MS_TO_KN = 3600.0 / 1852.0


def test_bind_ignores_async_client_transport():
    from weather_pipeline import bind_weather_transport, weather_http_transport

    class FakeAsyncTransport:
        pass

    bind_weather_transport(FakeAsyncTransport())
    assert weather_http_transport() is None


def test_same_quarter_degree_shares_a_cell():
    assert weather_cell(10.01, 20.01) == weather_cell(10.12, 20.12)
    assert weather_cell(10.01, 20.01) != weather_cell(10.30, 20.30)


def test_cache_key_includes_provider_and_cycle():
    when = datetime(2026, 9, 16, 15, tzinfo=timezone.utc)
    a = cache_key("wind", 10.01, 20.01, when)
    b = cache_key("wave", 10.01, 20.01, when)
    later = cache_key("wind", 10.01, 20.01, when + timedelta(hours=12))
    assert a[0] == "wind"
    assert a[1:] == b[1:]
    assert a[0] != b[0]
    assert a[3] == forecast_cycle(when)
    assert later[3] != a[3]


def test_snapshot_is_immediate_and_deduplicates_loader():
    pipe = WeatherPipeline()
    calls = []
    started = threading.Event()
    release = threading.Event()

    def loader():
        started.set()
        release.wait(1)
        calls.append(1)
        return {"ok": True, "n": len(calls)}

    first = pipe.snapshot("wind", 10.01, 20.01, loader)
    second = pipe.snapshot("wind", 10.12, 20.12, loader)
    assert first["status"] == "pending"
    assert first["refreshing"] is True
    assert second["status"] == "pending"
    assert started.wait(1)
    release.set()
    ready = pipe.wait_ready("wind", 10.01, 20.01, timeout=2)
    cached = pipe.snapshot("wind", 10.12, 20.12, loader)
    assert ready["status"] == "ready"
    assert ready["ok"] is True
    assert cached["status"] == "ready"
    assert cached["n"] == 1
    assert calls == [1]


def test_new_cycle_keeps_stale_ready_and_refreshes():
    pipe = WeatherPipeline()
    early = datetime(2026, 9, 16, 8, tzinfo=timezone.utc)
    late = datetime(2026, 9, 16, 20, tzinfo=timezone.utc)
    assert to_iso(last_ready_cycle(early)) != to_iso(last_ready_cycle(late))

    pipe.snapshot("wind", 46.15, -1.16, lambda: {"wind_speed_knots": 8}, when=early)
    first = pipe.wait_ready("wind", 46.15, -1.16, when=early, timeout=2)
    assert first["status"] == "ready"
    assert first["wind_speed_knots"] == 8

    started = threading.Event()
    release = threading.Event()

    def next_loader():
        started.set()
        release.wait(1)
        return {"wind_speed_knots": 14}

    stale = pipe.snapshot("wind", 46.15, -1.16, next_loader, when=late)
    assert stale["status"] == "ready"
    assert stale["refreshing"] is True
    assert stale["wind_speed_knots"] == 8
    assert stale["cycle"] == to_iso(last_ready_cycle(early))
    assert started.wait(1)
    release.set()
    fresh = pipe.wait_ready("wind", 46.15, -1.16, when=late, timeout=2)
    assert fresh["status"] == "ready"
    assert fresh["wind_speed_knots"] == 14
    assert fresh["cycle"] == to_iso(last_ready_cycle(late))


def test_kick_does_not_start_a_second_thread():
    pipe = WeatherPipeline()
    release = threading.Event()

    def loader():
        release.wait(1)
        return {"ok": True}

    assert pipe.kick("official-grib", 46.15, -1.16, loader) is True
    assert pipe.kick("official-grib", 46.15, -1.16, loader) is False
    assert pipe.provider_busy("official-grib") is True
    release.set()
    pipe.wait_ready("official-grib", 46.15, -1.16, timeout=2)
    assert pipe.provider_busy("official-grib") is False


def test_error_is_durable_until_forced():
    pipe = WeatherPipeline()

    def boom():
        raise RuntimeError("down")

    pipe.snapshot("wind", 1.0, 2.0, boom)
    err = pipe.wait_ready("wind", 1.0, 2.0, timeout=2)
    assert err["status"] == "error"
    again = pipe.snapshot("wind", 1.0, 2.0, boom)
    assert again["status"] == "error"
    assert again["refreshing"] is False
    assert pipe.kick("wind", 1.0, 2.0, boom) is False


def test_snapshot_group_pending_until_every_product_ready():
    pipe = WeatherPipeline()
    release = threading.Event()

    def load(kind):
        def _load():
            release.wait(1)
            return {"source": kind}
        return _load

    body = pipe.snapshot_group(
        (
            ("wind", "wind", load("wind")),
            ("wave", "wave", load("wave")),
        ),
        10.0,
        20.0,
    )
    assert body["status"] == "pending"
    assert body["wind"]["status"] == "pending"
    release.set()
    pipe.wait_providers(["wind", "wave"], 10.0, 20.0, timeout=2)
    ready = pipe.snapshot_group(
        (
            ("wind", "wind", load("wind")),
            ("wave", "wave", load("wave")),
        ),
        10.0,
        20.0,
    )
    assert ready["status"] == "ready"
    assert ready["wind"]["source"] == "wind"
    assert ready["wave"]["source"] == "wave"


def test_weather_pipeline_flag_defaults_on(monkeypatch):
    # Consigne : « NAVIGUIDE_WEATHER_PIPELINE devient allumé par défaut » ;
    # « la variable à 0 remet l'ancien chemin tant qu'il existe ».
    monkeypatch.delenv("NAVIGUIDE_WEATHER_PIPELINE", raising=False)
    assert weather_pipeline_enabled() is True
    monkeypatch.setenv("NAVIGUIDE_WEATHER_PIPELINE", "")
    assert weather_pipeline_enabled() is True
    monkeypatch.setenv("NAVIGUIDE_WEATHER_PIPELINE", "1")
    assert weather_pipeline_enabled() is True
    monkeypatch.setenv("NAVIGUIDE_WEATHER_PIPELINE", "0")
    assert weather_pipeline_enabled() is False
    monkeypatch.setenv("NAVIGUIDE_WEATHER_PIPELINE", "off")
    assert weather_pipeline_enabled() is False


def test_slow_provider_times_out_and_leaves_others_ready():
    queue = AsyncWeatherQueue(default_timeout_s=0.08)
    try:
        def slow():
            time.sleep(0.6)
            return {"hs": 2.0}

        def fast():
            return {"windKnots": 11}

        t0 = time.perf_counter()
        pending_slow = queue.snapshot("gfs-wave", 46.15, -1.16, slow)
        pending_fast = queue.snapshot("grib-wind", 46.15, -1.16, fast)
        assert time.perf_counter() - t0 < 0.2
        assert pending_slow["status"] == "pending"
        ready = queue.wait_layer("grib-wind", 46.15, -1.16, timeout=1)
        assert ready["status"] == "ready"
        assert ready["windKnots"] == 11
        unavailable = queue.wait_layer("gfs-wave", 46.15, -1.16, timeout=1)
        assert unavailable["status"] == "unavailable"
        assert unavailable["reason"] == "timeout"
    finally:
        queue.close()


def test_failing_provider_becomes_unavailable_without_raising():
    queue = AsyncWeatherQueue(default_timeout_s=1)
    try:
        def boom():
            raise RuntimeError("down")

        first = queue.snapshot("grib-wind", 1.0, 2.0, boom)
        assert first["status"] in {"pending", "unavailable"}
        done = queue.wait_layer("grib-wind", 1.0, 2.0, timeout=1)
        assert done["status"] == "unavailable"
        assert done["reason"] == "RuntimeError"
        again = queue.snapshot("grib-wind", 1.0, 2.0, boom)
        assert again["status"] == "unavailable"
    finally:
        queue.close()


def test_cache_hit_skips_loader_for_same_cell_and_hour():
    queue = AsyncWeatherQueue(default_timeout_s=1)
    when = datetime(2026, 10, 18, 8, 20, tzinfo=timezone.utc)
    calls = []
    try:
        def loader():
            calls.append(1)
            return {"windKnots": 8}

        same = layer_cache_key("grib-wind", 10.01, 20.01, when)
        assert same == layer_cache_key("grib-wind", 10.12, 20.12, when)
        assert same[2] != layer_cache_key("grib-wind", 10.01, 20.01, when + timedelta(hours=2))[2]
        queued = queue.snapshot("grib-wind", 10.01, 20.01, loader, when=when)
        assert queued["status"] in {"pending", "ready"}
        ready = queue.wait_layer("grib-wind", 10.01, 20.01, when=when, timeout=1)
        assert ready["status"] == "ready"
        assert ready["windKnots"] == 8
        hit = queue.snapshot("grib-wind", 10.12, 20.12, loader, when=when)
        assert hit["status"] == "ready"
        assert hit["windKnots"] == 8
        assert calls == [1]
    finally:
        queue.close()


def test_flagged_grib_kick_returns_before_a_slow_provider(monkeypatch):
    import voyage_api

    monkeypatch.setenv("NAVIGUIDE_WEATHER_PIPELINE", "1")
    release = threading.Event()

    def hang(*_args, **_kwargs):
        release.wait(2)
        return None

    monkeypatch.setattr(voyage_api, "maybe_refresh_official", hang)
    queue = AsyncWeatherQueue(default_timeout_s=0.08)
    monkeypatch.setattr(voyage_api, "get_async_weather_queue", lambda: queue)
    try:
        t0 = time.perf_counter()
        assert voyage_api._kick_official_grib({"lat": 46.15, "lon": -1.16}) is True
        assert time.perf_counter() - t0 < 0.3
        assert voyage_api._kick_official_grib({"lat": 46.15, "lon": -1.16}) is False
        done = queue.wait_layer("grib-wind", 46.15, -1.16, timeout=1)
        assert done["status"] == "unavailable"
        assert done["reason"] == "timeout"
        body = voyage_api._pending_grib(None, {"lat": 46.15, "lon": -1.16}, datetime.now(timezone.utc), refreshing=False)
        assert body["layers"]["gribWind"]["status"] == "unavailable"
        # L'ancien chemin qui omettait `layers` est retiré : off sert le même état.
        assert _body_with_flag_off(monkeypatch)["layers"]["gribWind"]["status"] == "unavailable"
    finally:
        release.set()
        queue.close()


def _body_with_flag_off(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_WEATHER_PIPELINE", "off")
    import voyage_api
    return voyage_api._pending_grib(None, {"lat": 46.15, "lon": -1.16}, datetime.now(timezone.utc), refreshing=False)


def test_ms_to_kn_is_1852_metre_nautical_mile():
    """1 m/s → 1,943844 kn (horloge, hindcast, cube).

    3600/1852 = 1,94384449… ; le code tronque à 6 décimales (écart ~5e-7,
    noté dans la PR, non corrigé).
    """
    assert MS_TO_KN == 1.943844
    assert CLOCK_MS_TO_KN == 1.943844
    assert abs(MS_TO_KN - EXACT_MS_TO_KN) < 1e-6
    kn, _ = uv_to_current_to(1.0, 0.0)
    assert abs(kn - 1.943844) < 1e-6
    kn_w, _ = uv_to_wind_from(1.0, 0.0)
    assert abs(kn_w - 1.943844) < 1e-6
    kn_s, _ = knots_from_uv(1.0, 0.0)
    assert kn_s == 1.94


def test_current_uo_east_vo_zero_is_toward_90():
    """Courant « vers » : uo = 1, vo = 0 → 90° (est)."""
    kn, to_deg = uv_to_current_to(1.0, 0.0)
    assert abs(kn - MS_TO_KN) < 1e-6
    assert to_deg == 90.0
    _, to_north = uv_to_current_to(0.0, 1.0)
    assert to_north == 0.0


def test_wind_and_waves_use_meteorological_from():
    """Vent et vagues « de » : u = 1, v = 0 (vers l'est) vient de l'ouest = 270°."""
    kn, from_deg = uv_to_wind_from(1.0, 0.0)
    assert abs(kn - MS_TO_KN) < 1e-6
    assert from_deg == 270.0
    _, from_south = uv_to_wind_from(0.0, 1.0)
    assert from_south == 180.0
    # Même vecteur : « de » = « vers » + 180°. VMDR est déjà « de » (pas +180).
    _, to_deg = uv_to_current_to(1.0, 0.0)
    assert abs((from_deg - to_deg) % 360 - 180.0) < 1e-9
    from inspect import getsource
    import hindcast
    marine = getsource(hindcast._fetch_om_marine)
    assert "waveDirFromDeg" in marine
    assert "wave_direction" in marine
    assert "+ 180" not in marine
