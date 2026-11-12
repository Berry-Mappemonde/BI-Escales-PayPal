"""Audit item 1: GET /schedule must not rewrite every stop on every read.

The route made three database round trips per stop (17 stops, about 6 s on the hosted
demo) to write back schedule fields that had not changed. It now reads the milestones
once and writes only a stop that is missing or whose schedule fields changed. The
response is the same.
"""
from __future__ import annotations

import asyncio
import copy
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales import ledger as ledger_mod
from app.escales.naviguide_bridge import _meta_already_stored, local_schedule_export, sync_milestone_shells
from app.escales.pledges import get_ledger, reset_ledger
from app.routers.escales import router

STOP = "dep-la-rochelle"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin-key")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-12T08:00:00+00:00")
    monkeypatch.delenv("ESCALES_NAVIGUIDE_ENABLED", raising=False)
    reset_ledger()
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client
    reset_ledger()


@pytest.fixture
def ops(monkeypatch, api):
    """Counts the milestone reads and writes on the active ledger."""
    store = ledger_mod.get_ledger()
    ensure, listing = store.ensure_milestone, store.list_milestones
    seen = {"ensure": [], "list": 0}

    async def counted_ensure(milestone_id, meta=None):
        seen["ensure"].append(milestone_id)
        return await ensure(milestone_id, meta)

    async def counted_list():
        seen["list"] += 1
        return await listing()

    monkeypatch.setattr(store, "ensure_milestone", counted_ensure)
    monkeypatch.setattr(store, "list_milestones", counted_list)
    return seen


def _stored(milestone_id: str) -> dict:
    return asyncio.run(get_ledger().get_milestone(milestone_id))


def _reset(ops) -> None:
    ops["ensure"].clear()
    ops["list"] = 0


def test_first_read_creates_every_stop_once(api, ops):
    body = api.get("/api/escales/schedule").json()
    stops = [row["milestone_id"] for row in body["export"]["escales"]]
    assert len(stops) == 17
    assert sorted(ops["ensure"]) == sorted(stops)
    assert ops["list"] == 1


def test_a_warm_read_is_one_read_and_no_write(api, ops):
    api.get("/api/escales/schedule")
    _reset(ops)
    for _ in range(3):
        assert api.get("/api/escales/schedule").status_code == 200
    assert ops["ensure"] == []
    assert ops["list"] == 3


def test_the_answer_is_the_same_cold_and_warm(api):
    cold = api.get("/api/escales/schedule")
    warm = api.get("/api/escales/schedule")
    assert warm.content == cold.content
    assert list(cold.json()) == ["export", "milestones", "legs", "source", "clock", "prices", "logbook"]
    assert len(cold.json()["milestones"]) == 32
    assert len(cold.json()["legs"]) == 15


def test_a_warm_read_leaves_the_stored_stops_untouched(api):
    api.get("/api/escales/schedule")
    before = copy.deepcopy(_stored(STOP))
    api.get("/api/escales/schedule")
    assert _stored(STOP) == before  # including updated_at: nothing changed, nothing is stamped


def test_only_a_stop_whose_schedule_changed_is_written(api, ops):
    api.get("/api/escales/schedule")
    store = ledger_mod.get_ledger()
    # The stored arrival of one stop is out of date.
    store._milestones[STOP]["meta"]["arrival_iso"] = "2020-01-01T00:00:00+00:00"
    _reset(ops)
    api.get("/api/escales/schedule")
    assert ops["ensure"] == [STOP]
    fresh = next(row for row in local_schedule_export()["escales"] if row["milestone_id"] == STOP)
    assert _stored(STOP)["meta"]["arrival_iso"] == fresh["arrival_iso"]
    _reset(ops)
    api.get("/api/escales/schedule")
    assert ops["ensure"] == []


def test_a_missing_stop_is_created_again(api, ops):
    api.get("/api/escales/schedule")
    del ledger_mod.get_ledger()._milestones[STOP]
    _reset(ops)
    api.get("/api/escales/schedule")
    assert ops["ensure"] == [STOP]
    assert _stored(STOP)["meta"]["capture_on"] == "arrival"


def test_what_else_is_stored_on_a_stop_is_kept_and_causes_no_write(api, ops):
    api.get("/api/escales/schedule")
    store = ledger_mod.get_ledger()
    store._milestones[STOP]["meta"]["demo_cancelled"] = True
    store._milestones[STOP]["evidence"] = [{"met": True}]
    store._milestones[STOP]["proposal"] = {"decision": "capture"}
    _reset(ops)
    api.get("/api/escales/schedule")
    assert ops["ensure"] == []
    kept = _stored(STOP)
    assert kept["meta"]["demo_cancelled"] is True
    assert kept["evidence"] == [{"met": True}]
    assert kept["proposal"] == {"decision": "capture"}


def test_sync_returns_one_document_per_stop_in_schedule_order(api, ops):
    export = local_schedule_export()
    first = asyncio.run(sync_milestone_shells(export))
    again = asyncio.run(sync_milestone_shells(export))
    order = [row["milestone_id"] for row in export["escales"]]
    assert [doc["_id"] for doc in first] == order
    assert [doc["_id"] for doc in again] == order
    assert [doc["meta"] for doc in again] == [doc["meta"] for doc in first]


def test_the_milestone_routes_answer_as_before(api, ops):
    api.get("/api/escales/schedule")
    listed = api.get("/api/escales/milestones").json()
    assert STOP in [row["id"] for row in listed]
    synced = api.post("/api/escales/schedule/sync")
    assert synced.status_code == 200
    ids = [row["id"] for row in synced.json()]
    assert ids[:2] == ["dep-saint-maur-berry-indre", STOP]
    assert any(item.startswith("leg-") for item in ids)


@pytest.mark.parametrize(
    "stored, meta, expected",
    [
        ({"meta": {"a": 1, "b": 2}}, {"a": 1}, True),
        ({"meta": {"a": 1, "b": 2}}, {"a": 1, "b": 2}, True),
        ({"meta": {"a": 1}}, {"a": 2}, False),
        ({"meta": {"a": 1}}, {"a": 1, "b": None}, False),  # a key not stored yet is a change
        ({"meta": {"a": 1, "b": None}}, {"b": None}, True),
        ({"meta": None}, {"a": 1}, False),
        ({}, {"a": 1}, False),
        ({"meta": {}}, {}, True),
    ],
)
def test_meta_already_stored(stored, meta, expected):
    assert _meta_already_stored(stored, meta) is expected
