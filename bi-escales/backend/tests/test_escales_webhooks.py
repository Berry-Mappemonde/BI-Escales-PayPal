"""PayPal webhooks: signature verification (mocked) and idempotence."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.ledger import list_finance_entries
from app.escales.pledges import reset_ledger
from app.routers.escales import router, set_paypal_client_factory, webhooks_router


PAYLOAD = {
    "id": "WH-TEST-EVENT",
    "event_type": "CHECKOUT.ORDER.APPROVED",
    "resource": {
        "id": "ORDER1",
        "supplementary_data": {"related_ids": {"order_id": "ORDER1"}},
    },
}

HEADERS = {
    "PAYPAL-TRANSMISSION-ID": "T-123",
    "PAYPAL-TRANSMISSION-TIME": "2026-11-04T00:00:00Z",
    "PAYPAL-TRANSMISSION-SIG": "sig",
    "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT",
    "PAYPAL-AUTH-ALGO": "SHA256withRSA",
    "Content-Type": "application/json",
}


class FakePayPal:
    def __init__(self):
        self.verify_calls = 0

    def verify_webhook_signature(self, **kwargs):
        self.verify_calls += 1
        assert kwargs["webhook_id"] == "WH-DEMO"
        return {"verification_status": "SUCCESS"}

    def create_authorize_order(self, *args, **kwargs):
        raise AssertionError("webhook handler must not create orders")


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_WEBHOOKS_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-DEMO")
    reset_ledger()
    fake = FakePayPal()
    set_paypal_client_factory(lambda: fake)
    app = FastAPI()
    app.include_router(router)
    app.include_router(webhooks_router)
    with TestClient(app) as client:
        yield client, fake
    set_paypal_client_factory(None)
    reset_ledger()


def test_webhook_disabled_returns_404(api, monkeypatch):
    monkeypatch.delenv("ESCALES_WEBHOOKS_ENABLED", raising=False)
    client, _fake = api
    response = client.post("/api/escales/webhooks/paypal", headers=HEADERS, content=json.dumps(PAYLOAD))
    assert response.status_code == 404


def test_webhook_verifies_and_is_idempotent(api):
    import asyncio

    client, fake = api
    first = client.post("/api/escales/webhooks/paypal", headers=HEADERS, content=json.dumps(PAYLOAD))
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["accepted"] is True
    assert body["event_type"] == "CHECKOUT.ORDER.APPROVED"
    assert fake.verify_calls == 1

    second = client.post("/api/escales/webhooks/paypal", headers=HEADERS, content=json.dumps(PAYLOAD))
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert fake.verify_calls == 1

    entries = asyncio.run(list_finance_entries())
    assert sum(1 for entry in entries if entry["kind"] == "webhook_received") == 1


def test_webhook_rejects_bad_signature(api):
    client, fake = api

    class BadPayPal(FakePayPal):
        def verify_webhook_signature(self, **kwargs):
            return {"verification_status": "FAILURE"}

    set_paypal_client_factory(lambda: BadPayPal())
    response = client.post("/api/escales/webhooks/paypal", headers=HEADERS, content=json.dumps(PAYLOAD))
    assert response.status_code == 401
    assert fake.verify_calls == 0
