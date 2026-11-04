"""R42 : interrupteur « Veille Tavily » — réglage persistant, effet réel sur watch_enabled()."""
import asyncio

from fastapi.testclient import TestClient

import escale_watch


def _client():
    import main  # noqa: PLC0415
    return TestClient(main.app)


def test_default_follows_env(monkeypatch):
    monkeypatch.delenv("NAVIGUIDE_TAVILY_WATCH", raising=False)
    assert escale_watch.watch_settings() == {"enabled": True, "default": True, "source": "env"}
    monkeypatch.setenv("NAVIGUIDE_TAVILY_WATCH", "0")
    assert escale_watch.watch_enabled() is False


def test_storage_error_fails_closed_even_when_default_is_on(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_TAVILY_WATCH", "1")
    monkeypatch.setattr(escale_watch, "_cache_get", lambda *a, **k: (_ for _ in ()).throw(OSError("store unavailable")))
    assert escale_watch.watch_settings() == {"enabled": False, "default": True, "source": "error"}
    assert escale_watch.watch_enabled() is False


def test_toggle_persists_and_drives_watch_enabled(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_TAVILY_WATCH", "1")
    c = _client()
    assert c.get("/escale/watch/settings").json()["enabled"] is True
    r = c.post("/escale/watch/settings", json={"enabled": False})
    assert r.status_code == 200 and r.json() == {"enabled": False, "default": True, "source": "setting"}
    assert escale_watch.watch_enabled() is False
    # Persistant : relu depuis pearl_store, pas d'un état en mémoire de la requête.
    assert escale_watch.watch_override() is False
    assert c.get("/escale/watch/settings").json()["enabled"] is False
    r = c.post("/escale/watch/settings", json={"enabled": True})
    assert r.json()["enabled"] is True and escale_watch.watch_enabled() is True


def test_disabling_setting_cancels_periodic_watch_loop(monkeypatch):
    import ici_warm  # noqa: PLC0415

    class RunningTask:
        cancelled = False

        def done(self):
            return False

        def cancel(self):
            self.cancelled = True

    task = RunningTask()
    monkeypatch.setattr(ici_warm, "_WATCH_LOOP_TASK", task)
    monkeypatch.setenv("NAVIGUIDE_TAVILY_WATCH", "1")

    import escale_api  # noqa: PLC0415
    response = asyncio.run(escale_api.post_watch_settings({"enabled": False}))

    assert response["enabled"] is False
    assert task.cancelled is True
    assert ici_warm._WATCH_LOOP_TASK is task


def test_on_during_cancellation_restarts_exactly_one_watch_loop(monkeypatch):
    import ici_warm  # noqa: PLC0415

    enabled = True
    started = []
    monkeypatch.setattr(escale_watch, "watch_enabled", lambda: enabled)

    async def waiting_loop():
        started.append(asyncio.current_task())
        await asyncio.Event().wait()

    monkeypatch.setattr(ici_warm, "_watch_loop", waiting_loop)

    async def scenario():
        nonlocal enabled
        ici_warm._WATCH_LOOP_TASK = None
        assert ici_warm.ensure_watch_loop()
        first = ici_warm._WATCH_LOOP_TASK
        await asyncio.sleep(0)
        enabled = False
        assert ici_warm.cancel_watch_loop()
        assert ici_warm._WATCH_LOOP_TASK is first
        enabled = True
        assert not ici_warm.ensure_watch_loop()
        await asyncio.gather(first, return_exceptions=True)
        await asyncio.sleep(0)
        second = ici_warm._WATCH_LOOP_TASK
        assert second is not None and second is not first
        assert len(started) == 2
        enabled = False
        second.cancel()
        await asyncio.gather(second, return_exceptions=True)
        ici_warm._WATCH_LOOP_TASK = None

    asyncio.run(scenario())


def test_off_means_zero_search(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_TAVILY_WATCH", "1")
    escale_watch.set_watch_override(False)
    import escale_api  # noqa: PLC0415
    called = []
    monkeypatch.setattr(escale_watch, "official_stop_in_window", lambda *a, **k: called.append(1))
    escale_api._schedule_escale_watch("Nouméa", -22.27, 166.44)
    assert called == []


def test_post_rejects_non_bool_and_requires_admin(monkeypatch):
    c = _client()
    assert c.post("/escale/watch/settings", json={"enabled": "yes"}).status_code == 400
    monkeypatch.setenv("NAVIGUIDE_ADMIN_SECRET", "s3")
    assert c.post("/escale/watch/settings", json={"enabled": False}).status_code == 401
    ok = c.post("/escale/watch/settings", json={"enabled": False}, headers={"X-Naviguide-Admin": "s3"})
    assert ok.status_code == 200
    reset = c.post("/escale/watch/settings", json={"enabled": None}, headers={"X-Naviguide-Admin": "s3"})
    assert reset.status_code == 200 and reset.json()["source"] == "env"
