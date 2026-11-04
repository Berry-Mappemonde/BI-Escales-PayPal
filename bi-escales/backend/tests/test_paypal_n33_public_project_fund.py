"""N33: public read-only per-project donation totals (no treasurer key)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.pledges import reset_ledger
from app.routers.escales import router, set_paypal_client_factory
from tests.test_escales_router import ADMIN, FakePayPal, _authorize, _create, _ready


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin-key")
    reset_ledger()
    yield
    reset_ledger()
    set_paypal_client_factory(None)


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin-key")
    reset_ledger()
    fake = FakePayPal()
    set_paypal_client_factory(lambda: fake)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client, fake
    set_paypal_client_factory(None)
    reset_ledger()


def test_public_project_fund_returns_amount_count_and_refunded_only(api):
    client, _fake = api
    _ready(
        client,
        "n33-a",
        {
            "amount_eur": "25.00",
            "description": "secret donor phrase",
            "milestone_id": "",
            "kind": "project_pledge",
            "target_id": "projet-ecole",
            "contributor": "someone@example.com",
        },
    )
    _ready(
        client,
        "n33-b",
        {
            "amount_eur": "10.00",
            "description": "another line",
            "milestone_id": "",
            "kind": "project_pledge",
            "target_id": "projet-ecole",
        },
    )
    public = client.get("/api/escales/projects/projet-ecole/fund")
    assert public.status_code == 200, public.text
    body = public.json()
    assert set(body.keys()) == {"project_id", "currency", "amount_eur", "donation_count", "refunded_eur"}
    assert body["project_id"] == "projet-ecole"
    assert body["currency"] == "EUR"
    assert body["amount_eur"] == "35.00"
    assert body["donation_count"] == 2
    assert body["refunded_eur"] == "0.00"

    _created, captured = _ready(
        client,
        "n33-ref",
        {
            "amount_eur": "25.00",
            "description": "refund me",
            "milestone_id": "",
            "kind": "project_pledge",
            "target_id": "projet-ecole",
        },
    )
    refund = client.post(
        f"/api/escales/pledges/{captured['id']}/refund",
        headers=ADMIN,
        json={"amount_eur": "5.00"},
    )
    assert refund.status_code == 200, refund.text
    after = client.get("/api/escales/projects/projet-ecole/fund").json()
    assert after["amount_eur"] == "60.00"
    assert after["donation_count"] == 3
    assert after["refunded_eur"] == "5.00"
    assert _created["order_id"] not in str(after)
    assert "someone@example.com" not in str(after)
    assert "secret donor" not in str(after)
    assert "pledge_id" not in str(after)


def test_public_project_fund_has_no_pii_and_detailed_milestone_route_stays_treasurer_only(api):
    client, _fake = api
    created = _create(
        client,
        "n33-pii",
        {
            "amount_eur": "12.00",
            "description": "PII description",
            "milestone_id": "",
            "kind": "project_pledge",
            "target_id": "projet-plastics",
            "contributor": "patron@example.com",
        },
    )
    assert created.status_code == 200
    pledge = created.json()
    authorized = _authorize(client, pledge["id"])
    assert authorized.status_code == 200

    locked = client.get("/api/escales/milestones/projet-plastics/fund")
    assert locked.status_code == 401

    detailed = client.get("/api/escales/milestones/projet-plastics/fund", headers=ADMIN)
    assert detailed.status_code == 200, detailed.text
    detail = detailed.json()
    assert "balance_eur" in detail
    assert "income_eur" in detail
    assert "authorized_eur" in detail
    assert "income" not in detail
    assert pledge["id"] not in str(detail)

    public = client.get("/api/escales/projects/projet-plastics/fund").json()
    assert public["amount_eur"] == "12.00"
    assert public["donation_count"] == 1
    forbidden = (
        pledge["id"],
        pledge["order_id"],
        "patron@example.com",
        "PII description",
        "approve_link",
        "contributor",
    )
    blob = str(public)
    for token in forbidden:
        assert token not in blob
