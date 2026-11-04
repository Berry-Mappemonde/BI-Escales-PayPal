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
    retry = dict(PAYLOAD)
    retry["id"] = "WH-TEST-EVENT-RETRY"
    accepted = client.post("/api/escales/webhooks/paypal", headers=fresh, content=json.dumps(retry))
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


def test_pending_webhook_writes_one_counted_capture(api, monkeypatch):
    """CAPTURE.COMPLETED on a pending pledge is one pledge_captured, with stop and amount."""
    import asyncio

    from app.escales.ledger import get_ledger, list_finance_entries, record_finance

    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin-key")

    async def seed():
        ledger = get_ledger()
        await ledger.save_pledge({
            "_id": "p-pend",
            "status": "pending",
            "intent": "AUTHORIZE",
            "payment_mode": "AUTHORIZE",
            "currency": "EUR",
            "amount_eur": "20.00",
            "description": "miles",
            "milestone_id": "dep-mayotte",
            "kind": "mile",
            "target_id": "mayotte",
            "order_id": "ORDER-PEND",
            "history": ["authorized", "pending"],
        })
        await ledger.save_pledge({
            "_id": "p-both",
            "status": "pending",
            "intent": "AUTHORIZE",
            "payment_mode": "AUTHORIZE",
            "currency": "EUR",
            "amount_eur": "30.00",
            "description": "deja",
            "milestone_id": "dep-dakar",
            "kind": "mile",
            "target_id": "dakar",
            "order_id": "ORDER-BOTH",
            "history": ["authorized", "pending"],
        })
        await record_finance(
            "pledge_captured",
            pledge_id="p-both",
            milestone_id="dep-dakar",
            amount_eur="30.00",
            currency="EUR",
            status="captured",
            actor="treasurer",
            pledge_kind="mile",
            target_id="dakar",
        )

    asyncio.run(seed())
    client, _fake = api

    def post(transmission, order_id, pledge_id):
        headers = dict(HEADERS)
        headers["PAYPAL-TRANSMISSION-ID"] = transmission
        payload = {
            "id": f"WH-{transmission}",
            "event_type": "PAYMENT.CAPTURE.COMPLETED",
            "resource": {
                "id": f"CAP-{transmission}",
                "status": "COMPLETED",
                "supplementary_data": {"related_ids": {"order_id": order_id}},
            },
        }
        response = client.post(
            "/api/escales/webhooks/paypal",
            headers=headers,
            content=json.dumps(payload),
        )
        assert response.status_code == 200, response.text
        return response.json()

    assert post("T-PEND", "ORDER-PEND", "p-pend")["pledge_id"] == "p-pend"
    again = post("T-PEND-2", "ORDER-PEND", "p-pend")
    assert again["pledge_id"] == "p-pend"
    post("T-BOTH", "ORDER-BOTH", "p-both")

    async def check():
        pend = await get_ledger().get_pledge("p-pend")
        entries = await list_finance_entries()
        return pend, entries

    pend, entries = asyncio.run(check())
    assert pend["status"] == "captured"
    captured = [row for row in entries if row["kind"] == "pledge_captured"]
    pend_rows = [row for row in captured if row["pledge_id"] == "p-pend"]
    both_rows = [row for row in captured if row["pledge_id"] == "p-both"]
    assert len(pend_rows) == 1
    assert pend_rows[0]["milestone_id"] == "dep-mayotte"
    assert pend_rows[0]["amount_eur"] == "20.00"
    assert "webhook_capture_completed" not in [row["kind"] for row in entries]
    assert len(both_rows) == 1
    assert both_rows[0]["amount_eur"] == "30.00"

    fund = client.get("/api/escales/milestones/dep-mayotte/fund")
    assert fund.status_code == 200
    assert fund.json()["income_eur"] == "20.00"
    assert fund.json()["captured_eur"] == "20.00"
    spent = client.post(
        "/api/escales/milestones/dep-mayotte/fund/spending",
        json={"amount_eur": "20.00", "description": "le fond compte"},
        headers={"x-admin-key": "test-admin-key"},
    )
    assert spent.status_code == 200, spent.text
    assert spent.json()["balance_eur"] == "0.00"
    over = client.post(
        "/api/escales/milestones/dep-mayotte/fund/spending",
        json={"amount_eur": "0.01", "description": "trop"},
        headers={"x-admin-key": "test-admin-key"},
    )
    assert over.status_code == 422


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


def _capture_event(event_id, event_type, order_id):
    return {
        "id": event_id,
        "event_type": event_type,
        "resource": {
            "id": f"CAP-{event_id}",
            "status": "COMPLETED" if event_type.endswith("COMPLETED") else "DENIED",
            "supplementary_data": {"related_ids": {"order_id": order_id}},
        },
    }


def test_pending_capture_follows_completed_and_denied(api):
    """COMPLETED writes one pledge_captured. DENIED marks capture_failed. Authorized stays."""
    import asyncio

    from app.escales.ledger import get_ledger, list_finance_entries

    async def seed():
        ledger = get_ledger()
        for pledge_id, order_id, status in (
            ("p-pending", "ORDER-PENDING", "pending"),
            ("p-denied", "ORDER-DENIED", "pending"),
            ("p-held", "ORDER-HELD", "authorized"),
            ("p-done", "ORDER-DONE", "captured"),
        ):
            await ledger.insert_pledge_once({
                "_id": pledge_id,
                "status": status,
                "intent": "AUTHORIZE",
                "payment_mode": "AUTHORIZE",
                "currency": "EUR",
                "amount_eur": "20.00",
                "description": "miles",
                "milestone_id": "dep-mayotte",
                "kind": "mile",
                "target_id": "mayotte",
                "order_id": order_id,
                "history": [status],
            })

    asyncio.run(seed())
    client, _fake = api

    def post(event_id, event_type, order_id, transmission):
        headers = dict(HEADERS)
        headers["PAYPAL-TRANSMISSION-ID"] = transmission
        payload = _capture_event(event_id, event_type, order_id)
        response = client.post(
            "/api/escales/webhooks/paypal", headers=headers, content=json.dumps(payload),
        )
        assert response.status_code == 200, response.text
        return response.json()

    first = post("WH-CAP-OK", "PAYMENT.CAPTURE.COMPLETED", "ORDER-PENDING", "T-CAP-OK")
    assert first["accepted"] is True
    again = post("WH-CAP-OK", "PAYMENT.CAPTURE.COMPLETED", "ORDER-PENDING", "T-CAP-OK-2")
    assert again["duplicate"] is True
    post("WH-CAP-NO", "PAYMENT.CAPTURE.DENIED", "ORDER-DENIED", "T-CAP-NO")
    post("WH-CAP-HELD", "PAYMENT.CAPTURE.COMPLETED", "ORDER-HELD", "T-CAP-HELD")
    post("WH-CAP-DONE", "PAYMENT.CAPTURE.COMPLETED", "ORDER-DONE", "T-CAP-DONE")

    async def statuses():
        ledger = get_ledger()
        entries = await list_finance_entries()
        rows = {
            name: (await ledger.get_pledge(name))["status"]
            for name in ("p-pending", "p-denied", "p-held", "p-done")
        }
        captured = [
            row for row in entries
            if row["kind"] == "pledge_captured" and row.get("pledge_id") == "p-pending"
        ]
        return rows, captured

    rows, captured = asyncio.run(statuses())
    assert rows == {
        "p-pending": "captured",
        "p-denied": "capture_failed",
        "p-held": "authorized",
        "p-done": "captured",
    }
    pending = asyncio.run(get_ledger().get_pledge("p-pending"))
    assert pending["capture_id"] == "CAP-WH-CAP-OK"
    assert pending["captured_at"]
    assert len(captured) == 1
    assert captured[0]["milestone_id"] == "dep-mayotte"
    assert captured[0]["amount_eur"] == "20.00"


def test_vault_payment_token_deleted_webhook_marks_pledges(api, monkeypatch):
    import asyncio

    from app.escales.ledger import get_ledger

    client, _fake = api
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-04-01T08:00:00Z")

    async def seed():
        ledger = get_ledger()
        await ledger.insert_pledge_once({
            "_id": "vault-wh",
            "status": "vaulted",
            "intent": "VAULT",
            "payment_mode": "VAULT",
            "vault_id": "VAULT-WH-1",
            "order_id": "ORD-VAULT",
            "milestone_id": "dep-mayotte",
            "amount_eur": "5.00",
            "currency": "EUR",
            "kind": "mile",
            "target_id": "dep-mayotte",
            "history": ["vaulted"],
        })

    asyncio.run(seed())

    payload = {
        "id": "WH-VAULT-DEL",
        "event_type": "VAULT.PAYMENT-TOKEN.DELETED",
        "resource": {"id": "VAULT-WH-1"},
    }
    headers = dict(HEADERS)
    headers["PAYPAL-TRANSMISSION-ID"] = "T-VAULT-DEL"

    first = client.post("/api/escales/webhooks/paypal", headers=headers, content=json.dumps(payload))
    assert first.status_code == 200, first.text
    assert first.json()["accepted"] is True

    async def read():
        return await get_ledger().get_pledge("vault-wh")

    row = asyncio.run(read())
    assert row["vault_token_deleted"] is True
    assert "webhook_vault_token_deleted" in row["history"]

    headers["PAYPAL-TRANSMISSION-ID"] = "T-VAULT-DEL-2"
    payload["id"] = "WH-VAULT-DEL-2"
    again = client.post("/api/escales/webhooks/paypal", headers=headers, content=json.dumps(payload))
    assert again.status_code == 200, again.text
    row2 = asyncio.run(read())
    assert row2["vault_token_deleted"] is True
    assert row2["history"].count("webhook_vault_token_deleted") == 2


def test_event_id_is_claimed_only_after_the_ledger_write(api, monkeypatch):
    import asyncio

    import app.escales.webhooks as webhooks
    from app.escales.ledger import get_ledger

    client, _fake = api
    calls = {"n": 0}
    real = webhooks._apply_event

    async def fail_once(event):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("ledger down")
        return await real(event)

    monkeypatch.setattr(webhooks, "_apply_event", fail_once)
    headers = dict(HEADERS)
    headers["PAYPAL-TRANSMISSION-ID"] = "T-CLAIM"
    payload = _capture_event("WH-CLAIM", "PAYMENT.CAPTURE.COMPLETED", "ORDER-NONE")
    with pytest.raises(RuntimeError, match="ledger down"):
        client.post("/api/escales/webhooks/paypal", headers=headers, content=json.dumps(payload))

    async def unclaimed():
        return await get_ledger().has_webhook("WH-CLAIM")

    assert asyncio.run(unclaimed()) is False
    monkeypatch.setattr(webhooks, "_apply_event", real)
    accepted = client.post(
        "/api/escales/webhooks/paypal", headers=headers, content=json.dumps(payload),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json().get("duplicate") is not True
    assert asyncio.run(unclaimed()) is True
