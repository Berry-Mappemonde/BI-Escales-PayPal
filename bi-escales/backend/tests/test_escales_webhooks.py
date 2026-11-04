"""PayPal webhooks: signature verification (mocked) and idempotence."""
from __future__ import annotations

import asyncio
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
    """Test double. Signature checks never call PayPal."""

    webhook_signature_mock = True

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


def _seed_authorized(order_id: str = "ORDER1", authorization_id: str = "AUTH1", pledge_id: str = "p1"):
    from app.escales.ledger import get_ledger

    async def run():
        await get_ledger().save_pledge({
            "_id": pledge_id,
            "status": "authorized",
            "order_id": order_id,
            "authorization_id": authorization_id,
            "history": ["created", "authorized"],
            "amount_eur": "20.00",
            "milestone_id": "dep-mayotte",
        })

    asyncio.run(run())


def test_webhook_updates_pledge_once_per_event_id(api):
    client, fake = api
    _seed_authorized()
    payload = {
        "id": "WH-CAP-1",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {
            "id": "CAP-1",
            "status": "COMPLETED",
            "supplementary_data": {"related_ids": {"order_id": "ORDER1", "authorization_id": "AUTH1"}},
        },
    }
    headers = {**HEADERS, "PAYPAL-TRANSMISSION-ID": "T-CAP-1"}
    first = client.post("/api/escales/webhooks/paypal", headers=headers, content=json.dumps(payload))
    assert first.status_code == 200, first.text
    assert first.json()["pledge_status"] == "settled"
    assert first.json()["updated"] is True

    headers_again = {**HEADERS, "PAYPAL-TRANSMISSION-ID": "T-CAP-2"}
    second = client.post("/api/escales/webhooks/paypal", headers=headers_again, content=json.dumps(payload))
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert fake.verify_calls == 1

    from app.escales.ledger import get_ledger

    async def check():
        doc = await get_ledger().get_pledge("p1")
        assert doc["status"] == "settled"
        assert doc["capture_id"] == "CAP-1"
        assert doc["paypal_status"] == "COMPLETED"
        assert doc["history"].count("settled") == 1

    asyncio.run(check())


def test_webhook_voided_pending_denied_and_ignores_custom_id(api):
    client, _fake = api
    _seed_authorized()
    voided = {
        "id": "WH-VOID-1",
        "event_type": "PAYMENT.AUTHORIZATION.VOIDED",
        "resource": {"id": "AUTH1", "status": "VOIDED"},
    }
    response = client.post(
        "/api/escales/webhooks/paypal",
        headers={**HEADERS, "PAYPAL-TRANSMISSION-ID": "T-VOID"},
        content=json.dumps(voided),
    )
    assert response.status_code == 200, response.text
    assert response.json()["pledge_status"] == "voided"

    from app.escales.ledger import get_ledger

    async def seed_more():
        await get_ledger().save_pledge({
            "_id": "p-pending",
            "status": "authorized",
            "order_id": "ORDER-P",
            "authorization_id": "AUTH-P",
            "history": ["authorized"],
            "amount_eur": "1.00",
            "milestone_id": "dep-mayotte",
        })
        await get_ledger().save_pledge({
            "_id": "p-denied",
            "status": "captured",
            "order_id": "ORDER-D",
            "authorization_id": "AUTH-D",
            "history": ["captured"],
            "amount_eur": "1.00",
            "milestone_id": "dep-mayotte",
        })
        await get_ledger().save_pledge({
            "_id": "p-custom",
            "status": "authorized",
            "order_id": "ORDER-C",
            "authorization_id": "AUTH-C",
            "history": ["authorized"],
            "amount_eur": "1.00",
            "milestone_id": "dep-mayotte",
        })

    asyncio.run(seed_more())
    pending = client.post(
        "/api/escales/webhooks/paypal",
        headers={**HEADERS, "PAYPAL-TRANSMISSION-ID": "T-PEND"},
        content=json.dumps({
            "id": "WH-PEND",
            "event_type": "PAYMENT.CAPTURE.PENDING",
            "resource": {
                "id": "CAP-P",
                "supplementary_data": {"related_ids": {"order_id": "ORDER-P"}},
            },
        }),
    )
    assert pending.json()["pledge_status"] == "pending"
    denied = client.post(
        "/api/escales/webhooks/paypal",
        headers={**HEADERS, "PAYPAL-TRANSMISSION-ID": "T-DENY"},
        content=json.dumps({
            "id": "WH-DENY",
            "event_type": "PAYMENT.CAPTURE.DENIED",
            "resource": {
                "id": "CAP-D",
                "supplementary_data": {"related_ids": {"order_id": "ORDER-D"}},
            },
        }),
    )
    assert denied.json()["pledge_status"] == "failed"
    ignored = client.post(
        "/api/escales/webhooks/paypal",
        headers={**HEADERS, "PAYPAL-TRANSMISSION-ID": "T-CUSTOM"},
        content=json.dumps({
            "id": "WH-CUSTOM",
            "event_type": "PAYMENT.CAPTURE.COMPLETED",
            "resource": {"id": "CAP-C", "custom_id": "ORDER-C"},
        }),
    )
    assert ignored.json()["updated"] is False

    async def check():
        ledger = get_ledger()
        assert (await ledger.get_pledge("p-pending"))["capture_id"] == "CAP-P"
        assert (await ledger.get_pledge("p-denied"))["status"] == "failed"
        assert (await ledger.get_pledge("p-custom"))["status"] == "authorized"

    asyncio.run(check())


def test_webhook_failure_does_not_consume_the_event_id(api, monkeypatch):
    import app.escales.webhooks as webhooks

    calls = {"n": 0}
    original = webhooks._apply_event

    async def flaky(event):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("ledger down")
        return await original(event)

    monkeypatch.setattr(webhooks, "_apply_event", flaky)
    client, fake = api
    with pytest.raises(RuntimeError):
        client.post("/api/escales/webhooks/paypal", headers=HEADERS, content=json.dumps(PAYLOAD))
    second = client.post("/api/escales/webhooks/paypal", headers=HEADERS, content=json.dumps(PAYLOAD))
    assert second.status_code == 200, second.text
    assert second.json().get("duplicate") is not True
    assert fake.verify_calls == 2
