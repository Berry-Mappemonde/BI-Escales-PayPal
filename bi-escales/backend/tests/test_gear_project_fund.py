"""Gear project public fund exposes goal and Channel3 metadata."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.gear_projects_catalog import funded_percent, lookup_project_fund_meta
from app.routers.escales import router, set_paypal_client_factory


def test_lookup_gear_goal_from_bundled_snapshot():
    meta = lookup_project_fund_meta("gear-dive-computer-expedition")
    assert meta is not None
    assert meta["goal_eur"] == "450.00"
    assert meta["project_kind"] == "gear_project"
    assert "channel3_buy_url" in meta


def test_funded_percent_caps_at_100():
    assert funded_percent("500.00", "450.00") == 100
    assert funded_percent("225.00", "450.00") == 50
    assert funded_percent("9999.00", "10000.00") == 99
    assert funded_percent("99.50", "100.00") == 99
    assert funded_percent("10000.00", "10000.00") == 100


def test_funded_percent_skips_mismatched_currency():
    assert funded_percent("10.00", "20.00", amount_currency="EUR", goal_currency="USD") is None


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


def test_public_fund_includes_goal_for_gear(api):
    res = api.get("/api/escales/projects/gear-dive-computer-expedition/fund")
    assert res.status_code == 200
    body = res.json()
    assert body["goal_eur"] == "450.00"
    assert "funded_pct" in body
    assert body.get("project_kind") == "gear_project"
