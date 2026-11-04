"""Lot N20–N23 (TEST_7db3a42 buyer report): webhooks, capture dates, fund refunds, cart i18n."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.captain import pledge_cart, suggest_pledge
from app.escales.paypal_client import PayPalError
from app.escales.pledges import reset_ledger
from app.routers.escales import router, set_paypal_client_factory, webhooks_router
from tests.test_escales_router import ADMIN, FakePayPal, MAYOTTE_PLEDGE, NEAR_MAYOTTE_CLOCK, PLEDGE, _authorize, _create, _ready, _ready_mayotte


PAYLOAD = {
    "id": "WH-N20",
    "event_type": "CHECKOUT.ORDER.APPROVED",
    "resource": {"id": "ORDER-N20"},
}

HEADERS = {
    "PAYPAL-TRANSMISSION-ID": "T-N20",
    "PAYPAL-TRANSMISSION-TIME": "2026-11-04T00:00:00Z",
    "PAYPAL-TRANSMISSION-SIG": "c2lnbmF0dXJl",
    "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT",
    "PAYPAL-AUTH-ALGO": "SHA256withRSA",
}


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_WEBHOOKS_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "n-admin")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-DEMO")
    reset_ledger()
    yield
    reset_ledger()
    set_paypal_client_factory(None)


def test_n20_webhook_verify_uses_env_webhook_id_and_raw_body():
    raw = json.dumps(PAYLOAD, separators=(",", ":")).encode()
    seen = {}

    class VerifySpy:
        def verify_webhook_signature(self, **kwargs):
            seen.update(kwargs)
            assert kwargs["webhook_id"] == "WH-DEMO"
            assert kwargs["raw_event"] == raw
            return {"verification_status": "SUCCESS"}

    set_paypal_client_factory(lambda: VerifySpy())
    app = FastAPI()
    app.include_router(router)
    app.include_router(webhooks_router)
    client = TestClient(app)
    response = client.post("/api/escales/webhooks/paypal", headers=HEADERS, content=raw)
    assert response.status_code == 200, response.text
    assert seen.get("transmission_id") == "T-N20"


def test_n20_webhook_rejection_records_verification_status(monkeypatch):
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "n-admin")
    raw = json.dumps(PAYLOAD).encode()

    class FailVerify:
        def verify_webhook_signature(self, **kwargs):
            raise PayPalError(
                400,
                json.dumps({"name": "INVALID_REQUEST", "verification_status": "FAILURE"}),
            )

    set_paypal_client_factory(lambda: FailVerify())
    app = FastAPI()
    app.include_router(router)
    app.include_router(webhooks_router)
    client = TestClient(app)
    response = client.post(
        "/api/escales/webhooks/paypal",
        headers={**HEADERS, "PAYPAL-TRANSMISSION-ID": "T-REJECT"},
        content=raw,
    )
    assert response.status_code == 400
    assert "FAILURE" in response.text or "rejected" in response.text.lower()
    listed = client.get("/api/escales/webhooks/recent", headers={"x-admin-key": "n-admin"})
    assert listed.status_code == 200
    row = listed.json()["events"][0]
    assert row["outcome"] == "rejected"
    assert row.get("verification_status") == "FAILURE"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
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


def test_n21_capture_before_stop_arrival_is_refused(api, monkeypatch):
    client, _fake = api
    monkeypatch.setenv("ESCALES_CLOCK_NOW", NEAR_MAYOTTE_CLOCK)
    _created, authorized = _ready(client, "cap-early", MAYOTTE_PLEDGE)
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-01T08:00:00Z")
    early = client.post(f"/api/escales/pledges/{authorized['id']}/capture", headers=ADMIN)
    assert early.status_code == 422
    assert "stop arrival" in early.json()["detail"].lower()


def test_n21_capture_before_cabin_leg_departure_is_refused(api, monkeypatch):
    client, fake = api
    leg = "leg-la-rochelle-to-ajaccio-corse"
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-10T08:00:00Z")
    created = _create(client, "cabin-early-cap", {
        "amount_eur": "80.00",
        "description": "cabine",
        "milestone_id": leg,
        "kind": "cabin_leg",
        "target_id": leg,
    })
    assert created.status_code == 200, created.text
    authorized = _authorize(client, created.json()["id"])
    assert authorized.status_code == 200
    early = client.post(f"/api/escales/pledges/{authorized.json()['id']}/capture", headers=ADMIN)
    assert early.status_code == 422
    assert "leg departure" in early.json()["detail"].lower()
    assert all(call[0] != "capture" for call in fake.calls)


def test_n22_stop_fund_balance_subtracts_refunds(api, monkeypatch):
    client, _fake = api
    _created, authorized = _ready_mayotte(client, "fund-refund", monkeypatch)
    assert client.post(f"/api/escales/pledges/{authorized['id']}/capture", headers=ADMIN).status_code == 200
    before = client.get("/api/escales/milestones/dep-mayotte/fund").json()
    assert before["balance_eur"] == "20.00"
    refunded = client.post(
        f"/api/escales/pledges/{authorized['id']}/refund",
        json={"amount_eur": "5.00"},
        headers=ADMIN,
    )
    assert refunded.status_code == 200, refunded.text
    after = client.get("/api/escales/milestones/dep-mayotte/fund").json()
    assert after["income_eur"] == "20.00"
    assert after["balance_eur"] == "15.00"


def test_n23_captain_cart_uses_french_simulated_price_label():
    suggested = suggest_pledge("20 milles près de Mayotte", "fr")
    cart = pledge_cart("20 milles près de Mayotte", "fr", suggested)
    assert cart
    assert cart["price_label"] == "prix simulé"
    assert cart["lines"][0]["price_label"] == "prix simulé"
