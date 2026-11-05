"""Public GET /gear and seed catalog."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.gear_projects_catalog import load_gear_seed_collection, lookup_project_fund_meta, reset_gear_catalog_cache
from app.routers.escales import router, set_paypal_client_factory


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_gear_catalog_cache()
    yield
    reset_gear_catalog_cache()


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    set_paypal_client_factory(lambda: object())
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client
    set_paypal_client_factory(None)


def test_seed_has_multiple_gear_items():
    features = load_gear_seed_collection().get("features") or []
    assert len(features) >= 3
    ids = {f["properties"]["id"] for f in features}
    assert "gear-dive-computer-expedition" in ids


def test_lookup_gear_goal_from_seed():
    meta = lookup_project_fund_meta("gear-dry-bag-expedition")
    assert meta is not None
    assert meta["goal_eur"] == "120.00"
    assert meta["project_kind"] == "gear_project"


def test_public_gear_route_returns_seed(api):
    res = api.get("/api/escales/gear")
    assert res.status_code == 200
    body = res.json()
    assert body["type"] == "FeatureCollection"
    assert len(body.get("features") or []) >= 3
    assert body.get("source") in {"seed", "seed+channel3"}


def test_channel3_merge_when_enabled(monkeypatch, api):
    monkeypatch.setenv("ESCALES_CHANNEL3_ENABLED", "1")

    async def fake_search(queries, **kwargs):
        return [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [1, 2]},
                "properties": {
                    "id": "gear-c3-test-live",
                    "title": "Live test",
                    "project_kind": "gear_project",
                    "goal_eur": "50.00",
                },
            }
        ]

    monkeypatch.setattr("app.channel3_client.search_gear_products", fake_search)
    reset_gear_catalog_cache()
    body = api.get("/api/escales/gear").json()
    ids = {row["properties"]["id"] for row in body.get("features") or []}
    assert "gear-c3-test-live" in ids
    assert body.get("source") == "seed+channel3"
