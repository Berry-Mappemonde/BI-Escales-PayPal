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
    "PAYPAL-TRANSMISSION-SIG": "c2lnbmF0dXJl",
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
    listed = client.get("/api/escales/webhooks/recent")
    assert listed.status_code == 404


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
    assert fake.verify_calls == 2

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


def test_signature_is_checked_before_the_duplicate(api):
    """A known transmission_id with a bad signature is rejected, not replayed."""
    client, fake = api
    first = client.post("/api/escales/webhooks/paypal", headers=HEADERS, content=json.dumps(PAYLOAD))
    assert first.status_code == 200
    assert fake.verify_calls == 1

    class BadPayPal(FakePayPal):
        def verify_webhook_signature(self, **kwargs):
            fake.verify_calls += 1
            return {"verification_status": "FAILURE"}

    set_paypal_client_factory(lambda: BadPayPal())
    replay = client.post("/api/escales/webhooks/paypal", headers=HEADERS, content=json.dumps(PAYLOAD))
    assert replay.status_code == 401
    assert replay.json().get("duplicate") is not True
    assert fake.verify_calls == 2

    fresh = dict(HEADERS)
    fresh["PAYPAL-TRANSMISSION-ID"] = "T-FRESH"
    denied = client.post("/api/escales/webhooks/paypal", headers=fresh, content=json.dumps(PAYLOAD))
    assert denied.status_code == 401

    set_paypal_client_factory(lambda: fake)
    accepted = client.post("/api/escales/webhooks/paypal", headers=fresh, content=json.dumps(PAYLOAD))
    assert accepted.status_code == 200
    assert accepted.json()["accepted"] is True
    assert accepted.json().get("duplicate") is not True


def test_recent_webhooks_list_outcomes_for_the_treasurer(api, monkeypatch):
    import asyncio

    from app.escales.ledger import get_ledger

    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin-key")
    client, _fake = api

    async def seed():
        await get_ledger().insert_pledge_once({
            "_id": "pledge-order",
            "status": "authorized",
            "intent": "AUTHORIZE",
            "payment_mode": "AUTHORIZE",
            "currency": "EUR",
            "amount_eur": "10.00",
            "description": "10 milles",
            "milestone_id": "dep-mayotte",
            "kind": "mile",
            "target_id": "mayotte",
            "order_id": "ORDER1",
            "history": ["created"],
        })

    asyncio.run(seed())
    first = client.post("/api/escales/webhooks/paypal", headers=HEADERS, content=json.dumps(PAYLOAD))
    assert first.status_code == 200
    assert first.json()["pledge_id"] == "pledge-order"
    second = client.post("/api/escales/webhooks/paypal", headers=HEADERS, content=json.dumps(PAYLOAD))
    assert second.status_code == 200
    assert second.json()["duplicate"] is True

    class BadPayPal(FakePayPal):
        def verify_webhook_signature(self, **kwargs):
            return {"verification_status": "FAILURE"}

    set_paypal_client_factory(lambda: BadPayPal())
    bad_headers = dict(HEADERS)
    bad_headers["PAYPAL-TRANSMISSION-ID"] = "T-BAD"
    rejected = client.post(
        "/api/escales/webhooks/paypal", headers=bad_headers, content=json.dumps(PAYLOAD),
    )
    assert rejected.status_code == 401

    assert client.get("/api/escales/webhooks/recent").status_code == 401
    assert client.get(
        "/api/escales/webhooks/recent", headers={"x-admin-key": "wrong-admin-key"},
    ).status_code == 403
    listed = client.get("/api/escales/webhooks/recent", headers={"x-admin-key": "test-admin-key"})
    assert listed.status_code == 200
    events = listed.json()["events"]
    assert [row["outcome"] for row in events] == ["rejected", "duplicate", "accepted"]
    assert events[0]["transmission_id"] == "T-BAD"
    assert events[0]["pledge_id"] is None
    accepted = events[2]
    assert accepted["transmission_id"] == "T-123"
    assert accepted["event_type"] == "CHECKOUT.ORDER.APPROVED"
    assert accepted["resource_id"] == "ORDER1"
    assert accepted["pledge_id"] == "pledge-order"
    assert accepted["time"]
    assert events[1]["outcome"] == "duplicate"
    assert events[1]["pledge_id"] == "pledge-order"
    assert events[1]["transmission_id"] == "T-123"

    async def saved():
        return await get_ledger().get_pledge("pledge-order")

    doc = asyncio.run(saved())
    assert [row["outcome"] for row in doc["webhook_events"]] == ["accepted"]
    assert doc["webhook_events"][0]["transmission_id"] == "T-123"
    assert doc["webhook_events"][0]["resource_id"] == "ORDER1"
    assert doc["webhook_events"][0]["event_type"] == "CHECKOUT.ORDER.APPROVED"
    assert doc["webhook_events"][0]["time"]


def test_authorization_and_capture_read_related_order_id(api):
    import asyncio

    from app.escales.ledger import get_ledger
    from app.escales.webhooks import _order_id_from_resource

    auth_resource = {
        "id": "AUTH-1",
        "status": "CREATED",
        "supplementary_data": {"related_ids": {"order_id": "ORDER-AUTH"}},
        "links": [{
            "href": "https://api.sandbox.paypal.com/v2/payments/authorizations/AUTH-1",
            "rel": "self",
        }],
    }
    capture_resource = {
        "id": "CAP-1",
        "status": "COMPLETED",
        "supplementary_data": {
            "related_ids": {"order_id": "ORDER-CAP", "authorization_id": "AUTH-9"},
        },
        "links": [{
            "href": "https://api.sandbox.paypal.com/v2/payments/captures/CAP-1",
            "rel": "self",
        }],
    }
    assert _order_id_from_resource(auth_resource) == "ORDER-AUTH"
    assert _order_id_from_resource(capture_resource) == "ORDER-CAP"

    async def seed():
        ledger = get_ledger()
        for pledge_id, order_id in (("p-auth", "ORDER-AUTH"), ("p-cap", "ORDER-CAP")):
            await ledger.insert_pledge_once({
                "_id": pledge_id,
                "status": "authorized",
                "intent": "AUTHORIZE",
                "payment_mode": "AUTHORIZE",
                "currency": "EUR",
                "amount_eur": "10.00",
                "description": "miles",
                "milestone_id": "dep-mayotte",
                "kind": "mile",
                "target_id": "mayotte",
                "order_id": order_id,
                "history": ["created"],
            })

    asyncio.run(seed())
    client, _fake = api

    def post(event_type, resource, transmission, order_expected, pledge_expected):
        headers = dict(HEADERS)
        headers["PAYPAL-TRANSMISSION-ID"] = transmission
        payload = {"id": transmission, "event_type": event_type, "resource": resource}
        response = client.post(
            "/api/escales/webhooks/paypal", headers=headers, content=json.dumps(payload),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["order_id"] == order_expected
        assert body["pledge_id"] == pledge_expected

    post("PAYMENT.AUTHORIZATION.CREATED", auth_resource, "T-AUTH", "ORDER-AUTH", "p-auth")
    post("PAYMENT.CAPTURE.COMPLETED", capture_resource, "T-CAP", "ORDER-CAP", "p-cap")

    async def events():
        auth = await get_ledger().get_pledge("p-auth")
        capture = await get_ledger().get_pledge("p-cap")
        return auth["webhook_events"], capture["webhook_events"]

    auth_events, capture_events = asyncio.run(events())
    assert auth_events[0]["outcome"] == "accepted"
    assert auth_events[0]["event_type"] == "PAYMENT.AUTHORIZATION.CREATED"
    assert auth_events[0]["resource_id"] == "AUTH-1"
    assert capture_events[0]["event_type"] == "PAYMENT.CAPTURE.COMPLETED"
    assert capture_events[0]["resource_id"] == "CAP-1"
    assert capture_events[0]["outcome"] == "accepted"


def test_malformed_signature_or_cert_is_not_a_502(api):
    from app.escales.paypal_client import PayPalError

    client, fake = api
    bad_sig = dict(HEADERS)
    bad_sig["PAYPAL-TRANSMISSION-SIG"] = "not a signature!!"
    response = client.post(
        "/api/escales/webhooks/paypal", headers=bad_sig, content=json.dumps(PAYLOAD),
    )
    assert response.status_code == 400
    assert fake.verify_calls == 0

    bad_cert = dict(HEADERS)
    bad_cert["PAYPAL-TRANSMISSION-ID"] = "T-cert"
    bad_cert["PAYPAL-CERT-URL"] = "http://evil.example/cert.pem"
    response = client.post(
        "/api/escales/webhooks/paypal", headers=bad_cert, content=json.dumps(PAYLOAD),
    )
    assert response.status_code == 400
    assert fake.verify_calls == 0

    class BrokenPayPal(FakePayPal):
        def verify_webhook_signature(self, **kwargs):
            self.verify_calls += 1
            raise PayPalError(400, {"name": "INVALID_REQUEST", "message": "malformed signature"})

    broken = BrokenPayPal()
    set_paypal_client_factory(lambda: broken)
    paypal_headers = dict(HEADERS)
    paypal_headers["PAYPAL-TRANSMISSION-ID"] = "T-paypal-400"
    response = client.post(
        "/api/escales/webhooks/paypal", headers=paypal_headers, content=json.dumps(PAYLOAD),
    )
    assert response.status_code == 400
    assert response.status_code != 502
