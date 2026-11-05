"""Demo treasurer mode (ESCALES_DEMO_TREASURER + PAYPAL_ENV=sandbox)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.pledges import create_pledge, reset_ledger
from app.routers.escales import router, set_paypal_client_factory


@pytest.fixture(autouse=True)
def memory_env(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "super-secret-demo-key")
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")
    monkeypatch.delenv("ESCALES_DEMO_TREASURER", raising=False)
    reset_ledger()
    yield
    reset_ledger()
    set_paypal_client_factory(None)


@pytest.fixture
def api():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_features_exposes_demo_flag_off_by_default(api):
    body = api.get("/api/escales/features").json()
    assert body.get("demo_treasurer") is False
    blob = json.dumps(body)
    assert "super-secret-demo-key" not in blob


def test_get_pledges_without_key_refused_when_flag_unset(api):
    res = api.get("/api/escales/pledges")
    assert res.status_code == 401


def test_get_pledges_without_key_allowed_in_demo_sandbox(api, monkeypatch):
    monkeypatch.setenv("ESCALES_DEMO_TREASURER", "true")
    res = api.get("/api/escales/pledges")
    assert res.status_code == 200
    assert res.json() == []


def test_demo_refused_when_paypal_env_not_sandbox(api, monkeypatch):
    monkeypatch.setenv("ESCALES_DEMO_TREASURER", "true")
    monkeypatch.setenv("PAYPAL_ENV", "production")
    res = api.get("/api/escales/pledges")
    assert res.status_code == 403
    flags = api.get("/api/escales/features").json()
    assert flags.get("demo_treasurer") is False
    assert "super-secret-demo-key" not in json.dumps(flags)


def test_clock_settle_still_requires_admin_key_in_demo(api, monkeypatch):
    monkeypatch.setenv("ESCALES_DEMO_TREASURER", "true")
    res = api.post("/api/escales/clock/settle", json={})
    assert res.status_code == 401


def test_captain_review_approve_without_key_in_demo(api, monkeypatch):
    monkeypatch.setenv("ESCALES_DEMO_TREASURER", "true")
    res = api.post("/api/escales/milestones/dep-la-rochelle/captain-review/approve")
    assert res.status_code == 200
    assert res.json().get("approved") is True
