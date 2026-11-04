"""Navigation logbook and schedule ETA (NAVIGUIDE clock, no weather)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.navigation_logbook import navigation_logbook
from app.escales.naviguide_bridge import local_schedule_export
from app.escales.pledges import reset_ledger


@pytest.fixture(autouse=True)
def memory_store(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.delenv("ESCALES_NAVIGUIDE_ENABLED", raising=False)
    reset_ledger()
    yield
    reset_ledger()


def test_local_itinerary_clock_dates_monotonic():
    export = local_schedule_export()
    rows = sorted(export["escales"], key=lambda row: row["arrival_iso"])
    stamps = [row["arrival_iso"] for row in rows]
    assert stamps == sorted(stamps)
    assert rows[0]["milestone_id"] in {"dep-saint-maur-berry-indre", "dep-la-rochelle"}
    assert rows[-1]["milestone_id"] == "ret-la-rochelle"


def test_logbook_has_fr_en_entries_before_arrival():
    export = local_schedule_export()
    book = navigation_logbook(export)
    stop_id = "dep-fort-de-france-martinique"
    rows = book.get(stop_id)
    assert rows, f"expected logbook rows for {stop_id}"
    assert len(rows) >= 2
    arrival = next(row for row in export["escales"] if row["milestone_id"] == stop_id)["arrival_iso"]
    assert rows[-1]["kind"] == "stop"
    assert rows[-1]["t"].startswith(str(arrival)[:19])
    assert rows[0]["label_fr"].startswith("Position")
    assert rows[0]["label_en"].startswith("Position")
    assert "Fort-de-France" in rows[-1]["label_fr"]
    assert "Fort-de-France" in rows[-1]["label_en"]


def test_schedule_includes_logbook(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.routers.escales import router

    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        res = client.get("/api/escales/schedule")
        assert res.status_code == 200
        body = res.json()
        assert "logbook" in body
        assert body["logbook"]["dep-la-rochelle"]
