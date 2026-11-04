"""File météo asyncio : travail annulable, tâches gardées, pending périmé, GET sans force."""
import multiprocessing
import os
import threading
import time
from datetime import datetime, timezone

import pytest

import weather_pipeline
from weather_pipeline import (
    PENDING_MAX_AGE_S,
    AsyncWeatherQueue,
    ProcessJob,
    run_process_job,
)

FIX = "wx_job_fixtures"


def _no_live_child(timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not multiprocessing.active_children():
            return True
        time.sleep(0.05)
    return not multiprocessing.active_children()


def test_process_job_is_killed_at_the_deadline(tmp_path):
    marker = tmp_path / "late.txt"
    queue = AsyncWeatherQueue(default_timeout_s=0.5)
    try:
        job = ProcessJob(f"{FIX}:sleep_then_touch", str(marker), 1.5)
        assert queue.submit("gfs-wave", 46.15, -1.16, job) is True
        done = queue.wait_layer("gfs-wave", 46.15, -1.16, timeout=5)
        assert done["status"] == "unavailable"
        assert done["reason"] == "timeout"
        assert _no_live_child()
        time.sleep(1.6)
        assert not marker.exists(), "le processus enfant a continué après l'échéance"
    finally:
        queue.close()


def test_process_job_result_and_error():
    assert run_process_job(ProcessJob(f"{FIX}:answer", 9), timeout=30)["windKnots"] == 9
    with pytest.raises(weather_pipeline.ProviderError) as err:
        run_process_job(ProcessJob(f"{FIX}:fail"), timeout=30)
    assert err.value.reason == "ValueError"
    with pytest.raises(TimeoutError):
        run_process_job(ProcessJob(f"{FIX}:sleep_then_touch", os.devnull, 5), timeout=0.3)
    assert _no_live_child()


def test_queue_runs_process_jobs_ready_and_unavailable():
    queue = AsyncWeatherQueue(default_timeout_s=30)
    try:
        queue.submit("grib-wind", 10.0, 20.0, ProcessJob(f"{FIX}:answer", 12))
        queue.submit("gfs-wave", 10.0, 20.0, ProcessJob(f"{FIX}:fail"))
        ready = queue.wait_layer("grib-wind", 10.0, 20.0, timeout=30)
        assert ready["status"] == "ready"
        assert ready["windKnots"] == 12
        assert ready["pid"] != os.getpid()
        down = queue.wait_layer("gfs-wave", 10.0, 20.0, timeout=30)
        assert down["status"] == "unavailable"
        assert down["reason"] == "ValueError"
    finally:
        queue.close()


def test_cooperative_loader_stops_when_the_deadline_passes():
    stopped = threading.Event()
    queue = AsyncWeatherQueue(default_timeout_s=0.1)
    try:
        def loader(cancel):
            while not cancel.wait(0.01):
                pass
            stopped.set()
            return {}

        queue.submit("grib-wind", 1.0, 2.0, loader)
        done = queue.wait_layer("grib-wind", 1.0, 2.0, timeout=2)
        assert done["reason"] == "timeout"
        assert stopped.wait(1.0), "le chargeur n'a pas reçu l'arrêt"
    finally:
        queue.close()


def test_tasks_are_kept_until_done():
    release = threading.Event()
    queue = AsyncWeatherQueue(default_timeout_s=2)
    try:
        def loader(cancel):
            release.wait(1.5)
            return {"ok": 1}

        queue.submit("grib-wind", 3.0, 4.0, loader)
        deadline = time.monotonic() + 2
        while not queue._tasks and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(queue._tasks) == 1
        release.set()
        assert queue.wait_layer("grib-wind", 3.0, 4.0, timeout=2)["status"] == "ready"
        deadline = time.monotonic() + 2
        while queue._tasks and time.monotonic() < deadline:
            time.sleep(0.01)
        assert queue._tasks == set()
    finally:
        release.set()
        queue.close()


def test_old_pending_becomes_unavailable():
    assert PENDING_MAX_AGE_S > weather_pipeline.DEFAULT_PROVIDER_TIMEOUT_S
    release = threading.Event()
    queue = AsyncWeatherQueue(default_timeout_s=5, pending_max_age_s=0.1)
    try:
        def loader(cancel):
            release.wait(3)
            return {}

        queue.submit("grib-wind", 5.0, 6.0, loader)
        assert queue.cached_status("grib-wind", 5.0, 6.0) == "pending"
        assert queue.provider_busy("grib-wind") is True
        time.sleep(0.2)
        assert queue.cached_status("grib-wind", 5.0, 6.0) == "unavailable"
        assert queue.layer("grib-wind", 5.0, 6.0)["reason"] == "stale_pending"
        assert queue.provider_busy("grib-wind") is False
    finally:
        release.set()
        queue.close()


def test_a_running_job_is_never_started_twice_even_forced():
    release = threading.Event()
    queue = AsyncWeatherQueue(default_timeout_s=2)
    try:
        def loader(cancel):
            release.wait(1.5)
            return {}

        assert queue.submit("grib-wind", 7.0, 8.0, loader) is True
        assert queue.submit("grib-wind", 7.0, 8.0, loader, force=True) is False
    finally:
        release.set()
        queue.close()


class _Spy:
    def __init__(self, result=True, status=None):
        self.calls = []
        self.result = result
        self.status = status

    def submit(self, provider, lat, lon, loader, *, when=None, force=False):
        self.calls.append({"provider": provider, "loader": loader, "force": force})
        return self.result

    def cached_status(self, *_a, **_k):
        return self.status

    def provider_busy(self, _provider):
        return False


AROUND = {"lat": 46.15, "lon": -1.16}


def test_flagged_get_never_forces_and_skips_fresh_data(monkeypatch):
    import voyage_api

    monkeypatch.setenv("NAVIGUIDE_WEATHER_PIPELINE", "1")
    spy = _Spy()
    monkeypatch.setattr(voyage_api, "get_async_weather_queue", lambda: spy)
    fresh = {"status": "ready"}
    monkeypatch.setattr(voyage_api, "load_latest", lambda *_a, **_k: fresh)
    monkeypatch.setattr(voyage_api, "is_stale", lambda record, when=None: False)
    assert voyage_api._kick_official_grib(dict(AROUND)) is False
    assert spy.calls == []

    monkeypatch.setattr(voyage_api, "is_stale", lambda record, when=None: True)
    assert voyage_api._kick_official_grib(dict(AROUND)) is True
    assert spy.calls[-1]["force"] is False
    job = spy.calls[-1]["loader"]
    assert isinstance(job, ProcessJob)
    assert job.target == "weather_jobs:refresh_official_grib"

    monkeypatch.setattr(voyage_api, "load_latest", lambda *_a, **_k: None)
    assert voyage_api._kick_official_grib(dict(AROUND)) is True
    assert spy.calls[-1]["force"] is False

    # Le rafraîchissement admin explicite reste forcé.
    assert voyage_api._kick_official_grib(dict(AROUND), force=True) is True
    assert spy.calls[-1]["force"] is True


def test_flag_off_still_uses_the_async_grib_job(monkeypatch):
    # L'ancien chemin à fils est retiré : off ne relance pas un kick forcé.
    import voyage_api
    from weather_pipeline import ProcessJob

    monkeypatch.setenv("NAVIGUIDE_WEATHER_PIPELINE", "off")
    monkeypatch.setattr(voyage_api, "load_latest", lambda *_a, **_k: None)
    seen = []

    class _Queue:
        def submit(self, provider, _lat, _lon, loader, **kwargs):
            seen.append((provider, loader, kwargs))
            return True

    monkeypatch.setattr(voyage_api, "get_async_weather_queue", lambda: _Queue())
    assert voyage_api._kick_official_grib(dict(AROUND)) is True
    assert seen[-1][0] == "grib-wind"
    assert isinstance(seen[-1][1], ProcessJob)
    assert seen[-1][1].target == "weather_jobs:refresh_official_grib"
    assert seen[-1][2]["force"] is False
    assert voyage_api._kick_official_grib(dict(AROUND), force=True) is True
    assert seen[-1][2]["force"] is True


def test_unavailable_wins_over_refreshing(monkeypatch):
    import voyage_api

    when = datetime(2026, 10, 18, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(voyage_api, "get_async_weather_queue", lambda: _Spy(status="unavailable"))
    assert voyage_api._grib_wind_layer(None, AROUND, when, refreshing=True) == "unavailable"
    monkeypatch.setattr(voyage_api, "get_async_weather_queue", lambda: _Spy(status="pending"))
    assert voyage_api._grib_wind_layer(None, AROUND, when, refreshing=False) == "pending"
    assert voyage_api._grib_wind_layer({"status": "ready"}, AROUND, when, refreshing=True) == "ready"
    monkeypatch.setattr(voyage_api, "get_async_weather_queue", lambda: _Spy(status=None))
    assert voyage_api._grib_wind_layer(None, AROUND, when, refreshing=True) == "pending"
    assert voyage_api._grib_wind_layer(None, AROUND, when, refreshing=False) == "unavailable"


def test_child_job_module_is_importable_by_name():
    import importlib

    fn = getattr(importlib.import_module("weather_jobs"), "refresh_official_grib")
    assert callable(fn)
