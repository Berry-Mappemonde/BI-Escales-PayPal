"""Pont NAVIGUIDE → jalons BI Escales."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.naviguide_bridge import (
    escales_to_milestones,
    fetch_naviguide_export,
    local_schedule_export,
    load_export_from_path,
    sync_milestone_shells,
)
from app.escales.pledges import reset_ledger


@pytest.fixture(autouse=True)
def memory_store(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.delenv("ESCALES_NAVIGUIDE_ENABLED", raising=False)
    monkeypatch.delenv("ESCALES_NAVIGUIDE_JSON", raising=False)
    reset_ledger()
    yield
    reset_ledger()


def test_escales_to_milestones_maps_ids():
    export = local_schedule_export()
    rows = escales_to_milestones(export)
    ids = [row["_id"] for row in rows]
    assert ids[0] == "dep-la-rochelle" or ids[0] == "dep-saint-maur-berry-indre"
    assert "dep-fort-de-france-martinique" in ids
    assert "dep-dzaoudzi-mayotte" in ids
    assert "ret-la-rochelle" in ids
    assert ids.index("dep-fort-de-france-martinique") < ids.index("dep-dzaoudzi-mayotte")
    assert rows[0]["source"] == "local"
    by_id = {row["_id"]: row for row in rows}
    shown = by_id["dep-fort-de-france-martinique"]
    assert shown["display_name"] == "Fort-de-France (Martinique)"
    assert "dep-" not in shown["display_name"].lower()
    assert shown["arrival_iso"].startswith("2026-") or shown["arrival_iso"].startswith("2027-")
    assert by_id["dep-la-rochelle"]["arrival_iso"].startswith("2026-11-12")
    assert by_id["dep-dzaoudzi-mayotte"]["arrival_iso"] > shown["arrival_iso"]


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
        assert payload["escales"][0]["milestone_id"] == "dep-saint-maur-berry-indre"

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
        docs = await sync_milestone_shells(local_schedule_export())
        assert len(docs) >= 16
        assert docs[0]["meta"]["title"]

    asyncio.run(run())


def test_load_export_from_path(tmp_path):
    path = tmp_path / "x.json"
    path.write_text(json.dumps({"escales": []}), encoding="utf-8")
    assert load_export_from_path(str(path))["escales"] == []


def test_clock_legs_one_per_stopover_pair(monkeypatch):
    """Jambes datées par l'horloge du 12 novembre 2026. Le départ de A décide."""
    from app.escales.naviguide_bridge import clock_legs, leg_departing_from, sync_leg_shells

    monkeypatch.delenv("ESCALES_CLOCK_START", raising=False)
    monkeypatch.delenv("ESCALES_ENV", raising=False)
    legs = clock_legs()
    assert len(legs) == 15
    ids = [leg["id"] for leg in legs]
    assert ids[0] == "leg-saint-maur-berry-indre-to-la-rochelle"
    sea = next(leg for leg in legs if leg["id"] == "leg-la-rochelle-to-ajaccio-corse")
    assert sea["kind"] == "sea"
    assert sea["capture_on"] == "departure"
    assert sea["departure_iso"].startswith("2026-11-12T12:00:00")
    land = legs[0]
    assert land["arrival_iso"] > land["departure_iso"]
    assert sea["from_name"] == "La Rochelle"
    assert sea["to_name"] == "Ajaccio (Corse)"
    ajaccio = next(leg for leg in legs if leg["from_slug"] == "ajaccio-corse")
    assert ajaccio["hold_hours"] == 72
    assert ajaccio["departure_iso"].startswith("2026-12-02T02:02:54")
    assert leg_departing_from("Fort-de-France")["id"] == (
        "leg-fort-de-france-martinique-to-pointe-a-pitre-guadeloupe"
    )
    assert leg_departing_from("Mayotte")["from_slug"] == "dzaoudzi-mayotte"
    back = legs[-1]
    assert back["id"] == "leg-europa-taaf-to-la-rochelle"
    assert back["to_slug"] == "ret-la-rochelle"
    assert back["arrival_iso"].startswith("2027-08-27")
    assert back["arrival_iso"] > legs[0]["arrival_iso"]

    monkeypatch.setenv("ESCALES_ENV", "development")
    monkeypatch.setenv("ESCALES_CLOCK_START", "2026-12-01")
    shifted = next(
        leg for leg in clock_legs() if leg["id"] == "leg-la-rochelle-to-ajaccio-corse"
    )
    assert shifted["departure_iso"].startswith("2026-12-01T12:00:00")

    async def run():
        docs = await sync_leg_shells()
        assert len(docs) == 15
        assert docs[1]["meta"]["capture_on"] == "departure"
        assert docs[1]["meta"]["departure_iso"].startswith("2026-12-01T12:00:00")

    asyncio.run(run())


def test_no_milestone_is_dated_before_the_november_clock(monkeypatch):
    """L'ancien dep-mayotte au 2026-09-01 n'est plus sur l'horloge du 12/11."""
    from app.escales.naviguide_bridge import clock_legs

    monkeypatch.delenv("ESCALES_CLOCK_START", raising=False)
    monkeypatch.delenv("ESCALES_ENV", raising=False)
    floor = "2026-11-12"
    export = local_schedule_export()
    ids = [item["milestone_id"] for item in export["escales"]]
    assert "dep-mayotte" not in ids
    mayotte = next(item for item in export["escales"] if item["milestone_id"] == "dep-dzaoudzi-mayotte")
    assert not str(mayotte["arrival_iso"]).startswith("2026-09-01")
    assert mayotte["arrival_iso"] >= floor
    for item in export["escales"]:
        assert item["arrival_iso"] >= floor, item["milestone_id"]
    for leg in clock_legs():
        assert leg["departure_iso"] >= floor, leg["id"]
        assert leg["arrival_iso"] >= floor, leg["id"]
