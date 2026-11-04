"""Pont NAVIGUIDE → jalons BI Escales."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.ledger import get_ledger
from app.escales.naviguide_bridge import (
    escales_to_milestones,
    fetch_naviguide_export,
    local_schedule_export,
    load_export_from_path,
    reset_export_cache,
    sync_milestone_shells,
)
from app.escales.pledges import reset_ledger


@pytest.fixture(autouse=True)
def memory_store(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.delenv("ESCALES_NAVIGUIDE_ENABLED", raising=False)
    monkeypatch.delenv("ESCALES_NAVIGUIDE_JSON", raising=False)
    reset_ledger()
    reset_export_cache()
    yield
    reset_ledger()
    reset_export_cache()


def test_escales_to_milestones_maps_ids():
    export = local_schedule_export()
    rows = escales_to_milestones(export)
    ids = {row["_id"] for row in rows}
    assert ids == {"dep-mayotte", "dep-fort-de-france"}
    assert rows[0]["source"] == "local"


def test_fetch_naviguide_uses_local_when_flag_off():
    async def run():
        payload = await fetch_naviguide_export()
        assert payload["provider"] == "local"
        assert len(payload["escales"]) >= 2

    asyncio.run(run())


def test_fetch_naviguide_reads_json_file(monkeypatch, tmp_path):
    export = local_schedule_export()
    export["provider"] = "NAVIGUIDE"
    path = tmp_path / "escales.json"
    path.write_text(json.dumps(export), encoding="utf-8")
    monkeypatch.setenv("ESCALES_NAVIGUIDE_ENABLED", "1")
    monkeypatch.setenv("ESCALES_NAVIGUIDE_JSON", str(path))

    async def run():
        payload = await fetch_naviguide_export()
        assert payload["provider"] == "NAVIGUIDE"
        assert payload["escales"][0]["milestone_id"] == "dep-mayotte"

    asyncio.run(run())


def test_fetch_naviguide_http_mock(monkeypatch):
    export = local_schedule_export()
    export["provider"] = "NAVIGUIDE"

    class Handler(httpx.MockTransport):
        def __init__(self):
            super().__init__(self._handle)
            self.called = False

        def _handle(self, request: httpx.Request) -> httpx.Response:
            self.called = True
            assert request.url.path.endswith("/escales/export")
            return httpx.Response(200, json=export)

    monkeypatch.setenv("ESCALES_NAVIGUIDE_ENABLED", "1")
    monkeypatch.delenv("ESCALES_NAVIGUIDE_JSON", raising=False)

    async def run():
        transport = Handler()
        async with httpx.AsyncClient(transport=transport, base_url="http://sim.test") as client:
            monkeypatch.setenv("NAVIGUIDE_API_URL", "http://sim.test")
            payload = await fetch_naviguide_export(client=client)
        assert transport.called
        assert payload["provider"] == "NAVIGUIDE"

    asyncio.run(run())


def test_sync_milestone_shells_creates_docs():
    async def run():
        docs = await sync_milestone_shells(local_schedule_export(explicit_demo=True))
        assert len(docs) == 2
        assert docs[0]["meta"]["title"]

    asyncio.run(run())


def test_load_export_from_path(tmp_path):
    path = tmp_path / "x.json"
    path.write_text(json.dumps({"escales": []}), encoding="utf-8")
    assert load_export_from_path(str(path))["escales"] == []


def test_http_failure_keeps_real_dates_and_last_good_export(monkeypatch):
    monkeypatch.setenv("ESCALES_NAVIGUIDE_ENABLED", "1")
    monkeypatch.setenv("NAVIGUIDE_API_URL", "http://sim.test")
    calls = {"n": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={
                "provider": "NAVIGUIDE",
                "escales": [{
                    "milestone_id": "dep-mayotte",
                    "name": "Mayotte",
                    "arrival_iso": "2027-05-15T08:00:00+00:00",
                }],
            })
        return httpx.Response(503)

    async def run():
        await get_ledger().ensure_milestone(
            "dep-mayotte",
            meta={"arrival_iso": "2027-05-15T08:00:00+00:00", "title": "Mayotte"},
        )
        transport = httpx.MockTransport(handle)
        async with httpx.AsyncClient(transport=transport) as client:
            first = await fetch_naviguide_export(client=client)
            second = await fetch_naviguide_export(client=client)
        assert first["escales"][0]["arrival_iso"].startswith("2027-05-15")
        assert second.get("stale") is True
        assert second["escales"][0]["arrival_iso"].startswith("2027-05-15")
        assert "2026-09-01" not in json.dumps(second)
        await sync_milestone_shells(second)
        await sync_milestone_shells(local_schedule_export())
        saved = await get_ledger().get_milestone("dep-mayotte")
        assert saved["meta"]["arrival_iso"].startswith("2027-05-15")

    asyncio.run(run())
