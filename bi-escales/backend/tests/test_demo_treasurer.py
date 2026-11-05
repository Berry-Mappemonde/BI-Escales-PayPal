"""Demo treasurer mode (ESCALES_DEMO_TREASURER + PAYPAL_ENV=sandbox)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.pledges import create_pledge, get_ledger, reset_ledger
from tests.review_helpers import propose_capture_review
from app.routers.escales import router, set_paypal_client_factory


@pytest.fixture(autouse=True)
def memory_env(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "super-secret-demo-key")
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")
    monkeypatch.delenv("ESCALES_DEMO_TREASURER", raising=False)
    monkeypatch.delenv("ESCALES_ENV", raising=False)
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


def _seed_named_pledge(status: str = "authorized") -> str:
    import asyncio

    async def body():
        doc = await get_ledger().insert_pledge_once(
            {
                "_id": "demo-p-1",
                "status": status,
                "kind": "mile",
                "amount_eur": "12.00",
                "currency": "EUR",
                "milestone_id": "dep-la-rochelle",
                "target_id": "",
                "contributor": "Alice Secret-Name",
                "payer_email": "alice@example.com",
                "payer_name": "Alice S.",
                "order_id": "ORDER-XYZ",
                "authorization_id": "AUTH-XYZ",
                "approve_link": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-XYZ",
                "description": "Milles",
                "history": [status],
            }
        )
        return doc["_id"]

    return asyncio.run(body())


def test_demo_pledges_are_redacted_without_key(api, monkeypatch):
    monkeypatch.setenv("ESCALES_DEMO_TREASURER", "true")
    _seed_named_pledge()
    res = api.get("/api/escales/pledges")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 1
    blob = json.dumps(rows)
    for leaked in ("Alice", "alice@example.com", "ORDER-XYZ", "AUTH-XYZ", "contributor", "payer"):
        assert leaked not in blob
    assert rows[0]["status"] == "authorized"
    assert rows[0]["amount_eur"] == "12.00"


def test_pledges_with_key_are_complete_in_demo(api, monkeypatch):
    monkeypatch.setenv("ESCALES_DEMO_TREASURER", "true")
    _seed_named_pledge()
    res = api.get("/api/escales/pledges", headers={"x-admin-key": "super-secret-demo-key"})
    assert res.status_code == 200
    assert res.json()[0]["contributor"] == "Alice Secret-Name"


def test_demo_refused_when_escales_env_is_production(api, monkeypatch):
    monkeypatch.setenv("ESCALES_DEMO_TREASURER", "true")
    monkeypatch.setenv("ESCALES_ENV", "production")
    _seed_named_pledge()
    res = api.get("/api/escales/pledges")
    assert res.status_code == 403
    assert "Alice" not in res.text
    assert api.get("/api/escales/features").json().get("demo_treasurer") is False


@pytest.mark.parametrize("path", ["capture", "void"])
def test_money_routes_need_key_even_in_demo(api, monkeypatch, path):
    monkeypatch.setenv("ESCALES_DEMO_TREASURER", "true")
    pledge_id = _seed_named_pledge()
    called = []
    set_paypal_client_factory(lambda: called.append(1) or object())
    res = api.post(f"/api/escales/pledges/{pledge_id}/{path}", json={})
    assert res.status_code == 401
    assert called == []


def test_captain_review_approve_needs_key_in_demo(api, monkeypatch):
    monkeypatch.setenv("ESCALES_DEMO_TREASURER", "true")
    res = api.post("/api/escales/milestones/dep-la-rochelle/captain-review/approve")
    assert res.status_code == 401


def test_captain_review_approve_with_key_in_demo(api, monkeypatch):
    monkeypatch.setenv("ESCALES_DEMO_TREASURER", "true")
    import asyncio

    asyncio.run(propose_capture_review("dep-la-rochelle"))
    res = api.post(
        "/api/escales/milestones/dep-la-rochelle/captain-review/approve",
        headers={"x-admin-key": "super-secret-demo-key"},
    )
    assert res.status_code == 200
    assert res.json().get("approved") is True
