"""P2 PayPal lot: disputes, invoicing, subscriptions, webhooks, eligibility."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.paypal_p2_eligibility import PAY_LATER_FR_MIN_EUR, p2_eligibility_report
from app.escales.paypal_subscriptions import ensure_crew_supporter_catalog
from app.escales.pledges import reset_ledger
from app.escales.webhooks import verify_and_process
from app.routers.escales import router, set_paypal_client_factory


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "p2-admin")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "wh-test")
    reset_ledger()
    yield
    reset_ledger()
    set_paypal_client_factory(None)


class P2Spy:
    def __init__(self):
        self.calls = []

    def list_disputes(self, **kwargs):
        self.calls.append(("list_disputes", kwargs))
        return {"items": [{"dispute_id": "PP-D-1", "status": "OPEN"}]}

    def get_dispute(self, dispute_id):
        self.calls.append(("get_dispute", dispute_id))
        return {"dispute_id": dispute_id, "status": "OPEN"}

    def accept_dispute_claim(self, dispute_id, *, note=""):
        self.calls.append(("accept", dispute_id, note))
        return {"dispute_id": dispute_id, "status": "RESOLVED"}

    def provide_dispute_evidence(self, dispute_id, *, notes, evidence_type="PROOF_OF_FULFILLMENT"):
        self.calls.append(("evidence", dispute_id, notes[:40]))
        return {"dispute_id": dispute_id}

    def list_invoices(self, *, page=1, page_size=20):
        self.calls.append(("list_invoices", page))
        return {"items": [{"id": "INV-1", "status": "SENT"}]}

    def create_invoice(self, **kwargs):
        self.calls.append(("create_invoice", kwargs))
        return {"id": "INV-NEW", "status": "DRAFT"}

    def send_invoice(self, invoice_id):
        self.calls.append(("send", invoice_id))
        return {"id": invoice_id}

    def remind_invoice(self, invoice_id):
        self.calls.append(("remind", invoice_id))
        return {"id": invoice_id}

    def cancel_invoice(self, invoice_id):
        self.calls.append(("cancel", invoice_id))
        return {"id": invoice_id}

    def create_billing_product(self, **kwargs):
        self.calls.append(("product", kwargs.get("name")))
        return {"id": "PROD-1"}

    def create_billing_plan(self, **kwargs):
        self.calls.append(("plan", kwargs.get("product_id")))
        return {"id": "PLAN-1"}

    def verify_webhook_signature(self, **kwargs):
        return {"verification_status": "SUCCESS"}

    def search_transactions(self, **kwargs):
        return {"transaction_details": []}

    def get_order(self, order_id):
        return {"id": order_id}

    def get_authorization(self, auth_id):
        return {"id": auth_id}


def test_p2_eligibility_report():
    report = p2_eligibility_report()
    assert report["pay_later"]["min_eur"] == PAY_LATER_FR_MIN_EUR
    assert report["venmo"]["eligible"] is False
    assert report["fastlane"]["eligible"] is False
    assert report["subscriptions"]["eligible"] is True


def test_dispute_routes_require_admin_and_call_paypal():
    spy = P2Spy()
    set_paypal_client_factory(lambda: spy)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.get("/api/escales/paypal/disputes").status_code == 401
    listed = client.get("/api/escales/paypal/disputes", headers={"x-admin-key": "p2-admin"})
    assert listed.status_code == 200
    assert listed.json()["paypal"]["items"][0]["dispute_id"] == "PP-D-1"
    detail = client.get("/api/escales/paypal/disputes/PP-D-1", headers={"x-admin-key": "p2-admin"})
    assert detail.status_code == 200
    accepted = client.post(
        "/api/escales/paypal/disputes/PP-D-1/accept-claim",
        headers={"x-admin-key": "p2-admin"},
        json={"note": "accept sandbox claim"},
    )
    assert accepted.status_code == 200
    evidence = client.post(
        "/api/escales/paypal/disputes/PP-D-1/provide-evidence",
        headers={"x-admin-key": "p2-admin"},
        json={"milestone_id": "dep-mayotte", "notes": "Schedule proof"},
    )
    assert evidence.status_code == 200
    assert ("evidence", "PP-D-1", "Schedule proof") in spy.calls


def test_invoicing_routes():
    spy = P2Spy()
    set_paypal_client_factory(lambda: spy)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    headers = {"x-admin-key": "p2-admin"}
    created = client.post(
        "/api/escales/paypal/invoices",
        headers=headers,
        json={
            "recipient_email": "partner@example.com",
            "amount_eur": "80.00",
            "description": "Cabin sponsor",
            "reference": "cab-1",
        },
    )
    assert created.status_code == 200
    assert client.post("/api/escales/paypal/invoices/INV-NEW/send", headers=headers).status_code == 200
    assert client.post("/api/escales/paypal/invoices/INV-NEW/remind", headers=headers).status_code == 200
    assert client.post("/api/escales/paypal/invoices/INV-NEW/cancel", headers=headers).status_code == 200
    listed = client.get("/api/escales/paypal/invoices", headers=headers)
    assert listed.status_code == 200


def test_subscription_setup_is_idempotent():
    async def run():
        spy = P2Spy()
        first = await ensure_crew_supporter_catalog(spy)
        second = await ensure_crew_supporter_catalog(spy)
        assert first["plan_id"] == "PLAN-1"
        assert second["idempotent"] is True
        assert spy.calls.count(("product", "Crew supporter")) == 1

    asyncio.run(run())


def test_subscription_setup_route():
    spy = P2Spy()
    set_paypal_client_factory(lambda: spy)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    headers = {"x-admin-key": "p2-admin"}
    one = client.post("/api/escales/paypal/subscriptions/setup", headers=headers)
    two = client.post("/api/escales/paypal/subscriptions/setup", headers=headers)
    assert one.status_code == 200
    assert two.json()["idempotent"] is True


def test_features_exposes_p2_eligibility():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    body = client.get("/api/escales/features").json()
    assert body["pay_later_min_eur"] == "30.00"
    assert body["p2_eligibility"]["disputes"]["eligible"] is True
    assert body["fastlane"] is False


def test_webhook_dispute_and_payout_batch():
    async def run():
        from app.escales.ledger import get_ledger

        spy = P2Spy()
        event = {
            "id": "evt-dispute-1",
            "event_type": "CUSTOMER.DISPUTE.CREATED",
            "resource": {"dispute_id": "PP-D-99", "status": "OPEN"},
        }
        raw = json.dumps(event).encode()
        headers = {
            "PAYPAL-TRANSMISSION-ID": "tx-d1",
            "PAYPAL-TRANSMISSION-TIME": "2026-11-04T12:00:00Z",
            "PAYPAL-TRANSMISSION-SIG": "c2lnbmF0dXJl",
            "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT",
            "PAYPAL-AUTH-ALGO": "SHA256withRSA",
        }
        result = await verify_and_process(raw_body=raw, headers=headers, client=spy)
        assert result["accepted"] is True
        payout = {
            "id": "evt-payout-1",
            "event_type": "PAYMENT.PAYOUTSBATCH.SUCCESS",
            "resource": {"batch_header": {"payout_batch_id": "BATCH-1"}, "batch_status": "SUCCESS"},
        }
        raw2 = json.dumps(payout).encode()
        await verify_and_process(
            raw_body=raw2,
            headers={**headers, "PAYPAL-TRANSMISSION-ID": "tx-p1"},
            client=spy,
        )
        finance = await get_ledger().list_finance()
        kinds = [row.get("kind") for row in finance]
        assert "paypal_dispute_snapshot" in kinds
        assert "payout_batch_webhook" in kinds

    asyncio.run(run())


def test_treasurer_chat_lists_invoices():
    spy = P2Spy()
    set_paypal_client_factory(lambda: spy)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    body = client.post(
        "/api/escales/captain/chat",
        json={"message": "List PayPal invoices for the treasurer", "lang": "en"},
        headers={"x-admin-key": "p2-admin"},
    ).json()
    assert body["model_source"] == "paypal_readonly_tools"
    assert "invoices" in body["reply"].lower()
