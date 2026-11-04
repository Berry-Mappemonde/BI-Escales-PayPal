"""Per-project fund balances (aggregate ``projet`` unchanged)."""

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


def test_per_project_fund_balance_keeps_aggregate_projet(api):
    client, _fake = api
    _created, captured_ecole = _ready(
        client,
        "bal-ecole",
        {
            "amount_eur": "25.00",
            "description": "École",
            "milestone_id": "",
            "kind": "project_pledge",
            "target_id": "projet-ecole",
        },
    )
    _ready(
        client,
        "bal-plastics",
        {
            "amount_eur": "10.00",
            "description": "Plastics",
            "milestone_id": "",
            "kind": "project_pledge",
            "target_id": "projet-plastics",
        },
    )
    aggregate = client.get("/api/escales/milestones/projet/fund", headers=ADMIN)
    assert aggregate.status_code == 200, aggregate.text
    assert aggregate.json()["balance_eur"] == "35.00"

    ecole = client.get("/api/escales/milestones/projet-ecole/fund", headers=ADMIN)
    assert ecole.status_code == 200, ecole.text
    assert ecole.json()["milestone_id"] == "projet-ecole"
    assert ecole.json()["balance_eur"] == "25.00"

    plastics = client.get("/api/escales/milestones/projet-plastics/fund", headers=ADMIN)
    assert plastics.status_code == 200
    assert plastics.json()["balance_eur"] == "10.00"

    assert client.get("/api/escales/milestones/nulle-part/fund").status_code == 404

    refund = client.post(
        f"/api/escales/pledges/{captured_ecole['id']}/refund",
        headers=ADMIN,
        json={"amount_eur": "5.00"},
    )
    assert refund.status_code == 200, refund.text

    ecole_after = client.get("/api/escales/milestones/projet-ecole/fund", headers=ADMIN).json()
    assert ecole_after["balance_eur"] == "20.00"
    assert client.get("/api/escales/milestones/projet/fund", headers=ADMIN).json()["balance_eur"] == "30.00"
    assert _created["id"] == captured_ecole["id"]


def test_project_pledge_response_includes_target_fund(api):
    client, _fake = api
    created = _create(
        client,
        "proj-fund-resp",
        {
            "amount_eur": "18.00",
            "description": "Projet",
            "milestone_id": "",
            "kind": "project_pledge",
            "target_id": "projet-ecole",
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["fund"] is not None
    assert body["fund"]["milestone_id"] == "projet-ecole"
    assert body["fund"]["balance_eur"] == "0.00"

    authorized = _authorize(client, body["id"])
    assert authorized.status_code == 200, authorized.text
    captured = authorized.json()
    assert captured["fund"] is not None
    assert captured["fund"]["milestone_id"] == "projet-ecole"
    assert captured["fund"]["balance_eur"] == "18.00"
