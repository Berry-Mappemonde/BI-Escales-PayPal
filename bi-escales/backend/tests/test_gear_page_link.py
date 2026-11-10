from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.channel3_urls import is_channel3_homepage_url
from app.gear_projects_catalog import load_gear_seed_collection, reset_gear_catalog_cache, sanitize_public_gear_collection
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


def test_seed_gear_has_no_channel3_homepage():
    features = load_gear_seed_collection().get("features") or []
    for feature in features:
        props = feature.get("properties") or {}
        for key in ("url", "channel3_buy_url"):
            value = props.get(key)
            if value:
                assert not is_channel3_homepage_url(value)
    dry = next(f for f in features if f["properties"]["id"] == "gear-dry-bag-expedition")
    assert "buy.trychannel3.com" in str(dry["properties"].get("channel3_buy_url") or "")


def test_public_gear_strips_buy_link_until_funded(api):
    body = api.get("/api/escales/gear").json()
    for feature in body.get("features") or []:
        props = feature.get("properties") or {}
        if str(props.get("project_kind") or "") != "gear_project":
            continue
        if props.get("goal_eur") or props.get("channel3_price") or props.get("channel3_price_eur"):
            assert "funded_pct" in props
        if not props.get("fully_funded"):
            assert "channel3_buy_url" not in props
            assert props.get("url") in (None, "")
        for key in ("url", "channel3_buy_url"):
            if props.get(key):
                assert not is_channel3_homepage_url(props[key])


def test_sanitize_strips_non_https_buy_url_even_when_fully_funded(monkeypatch):
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "id": "gear-test-js",
                    "goal_eur": "10.00",
                    "channel3_buy_url": "javascript:alert(1)",
                },
            }
        ],
    }

    async def _fund(_pid: str):
        return {"currency": "EUR", "captured_eur": "10.00", "amount_eur": "10.00"}

    monkeypatch.setattr("app.channel3_funding.fund_snapshot_for_project", _fund)
    out = asyncio.run(sanitize_public_gear_collection(payload))
    props = out["features"][0]["properties"]
    assert "channel3_buy_url" not in props
    assert props.get("url") in (None, "")


def test_sanitize_hides_homepage_even_if_marked_fully_funded(monkeypatch):
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "id": "gear-test",
                    "goal_eur": "10.00",
                    "channel3_buy_url": "https://trychannel3.com/",
                },
            }
        ],
    }

    async def _fund(_pid: str):
        return {"currency": "EUR", "captured_eur": "10.00", "amount_eur": "10.00"}

    monkeypatch.setattr("app.channel3_funding.fund_snapshot_for_project", _fund)
    out = asyncio.run(sanitize_public_gear_collection(payload))
    props = out["features"][0]["properties"]
    assert "channel3_buy_url" not in props
    assert props.get("url") in (None, "")
