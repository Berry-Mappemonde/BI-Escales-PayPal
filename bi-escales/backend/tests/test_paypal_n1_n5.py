"""Follow-up lot N1–N5: subscription upsert, draft invoice delete, Pay Later scope, chat tools, crew plan."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.paypal_client import PayPalError
from app.escales.paypal_reconcile import reconcile_paypal_ledger
from app.escales.paypal_subscriptions import ensure_crew_supporter_catalog, list_subscriptions_local
from app.escales.pledges import reset_ledger
from app.escales.webhooks import verify_and_process
from app.routers.escales import router, set_paypal_client_factory


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "n-admin")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "wh-n")
    reset_ledger()
    yield
    reset_ledger()
    set_paypal_client_factory(None)


class NSpy:
    def verify_webhook_signature(self, **kwargs):
        return {"verification_status": "SUCCESS"}

    def delete_invoice(self, invoice_id):
        return {"id": invoice_id, "status": "DELETED"}

    def cancel_invoice(self, invoice_id):
        raise PayPalError(
            422,
            {
                "name": "UNPROCESSABLE_ENTITY",
                "details": [{"issue": "INVOICE_STATUS_INVALID", "description": "Draft invoices cannot be cancelled"}],
            },
        )

    def create_billing_product(self, **kwargs):
        return {"id": "PROD-N"}

    def create_billing_plan(self, **kwargs):
        return {"id": "PLAN-N"}


def _webhook_headers(transmission_id: str) -> dict:
    return {
        "PAYPAL-TRANSMISSION-ID": transmission_id,
        "PAYPAL-TRANSMISSION-TIME": "2026-11-04T12:00:00Z",
        "PAYPAL-TRANSMISSION-SIG": "c2lnbmF0dXJl",
        "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT",
        "PAYPAL-AUTH-ALGO": "SHA256withRSA",
    }


def test_n1_subscription_webhook_keys_by_subscription_id_and_updates():
    async def run():
        spy = NSpy()
        activated = {
            "id": "evt-sub-act",
            "event_type": "BILLING.SUBSCRIPTION.ACTIVATED",
            "resource": {"id": "I-SUB-1", "plan_id": "P-CREW", "status": "ACTIVE"},
        }
        await verify_and_process(
            raw_body=json.dumps(activated).encode(),
            headers=_webhook_headers("tx-sub-1"),
            client=spy,
        )
        sale = {
            "id": "evt-sale-1",
            "event_type": "PAYMENT.SALE.COMPLETED",
            "resource": {
                "id": "SALE-999",
                "billing_agreement_id": "I-SUB-1",
                "plan_id": "P-CREW",
                "state": "completed",
            },
        }
        await verify_and_process(
            raw_body=json.dumps(sale).encode(),
            headers=_webhook_headers("tx-sale-1"),
            client=spy,
        )
        cancelled = {
            "id": "evt-sub-cancel",
            "event_type": "BILLING.SUBSCRIPTION.CANCELLED",
            "resource": {"id": "I-SUB-1", "plan_id": "P-CREW", "status": "CANCELLED"},
        }
        await verify_and_process(
            raw_body=json.dumps(cancelled).encode(),
            headers=_webhook_headers("tx-sub-2"),
            client=spy,
        )
        rows = await list_subscriptions_local()
        assert len(rows) == 1
        assert rows[0]["subscription_id"] == "I-SUB-1"
        assert rows[0]["status"] == "CANCELLED"

    asyncio.run(run())


def test_n2_delete_draft_invoice_and_cancel_surfaces_paypal_detail():
    spy = NSpy()
    set_paypal_client_factory(lambda: spy)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    headers = {"x-admin-key": "n-admin"}
    deleted = client.delete("/api/escales/paypal/invoices/INV-DRAFT", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "DELETED"
    cancel = client.post("/api/escales/paypal/invoices/INV-DRAFT/cancel", headers=headers)
    assert cancel.status_code == 422
    assert "INVOICE_STATUS_INVALID" in str(cancel.json().get("detail", ""))


def test_n4_show_me_paypal_transactions_without_lang():
    spy = type("C", (), {
        "get_order": lambda self, oid: {"id": oid},
        "get_authorization": lambda self, aid: {"id": aid},
        "list_disputes": lambda self, **k: {"items": []},
        "search_transactions": lambda self, **k: {"transaction_details": [{"x": 1}]},
        "list_invoices": lambda self, **k: {"items": []},
    })()
    set_paypal_client_factory(lambda: spy)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    body = client.post(
        "/api/escales/captain/chat",
        json={"message": "Show me the PayPal transactions for the treasurer"},
        headers={"x-admin-key": "n-admin", "Accept-Language": "fr-FR,fr;q=0.9"},
    ).json()
    assert body["model_source"] == "paypal_readonly_tools"
    assert "PayPal transactions" in body["reply"]


def test_n4_english_treasurer_question_without_lang():
    spy = type("C", (), {
        "get_order": lambda self, oid: {"id": oid},
        "get_authorization": lambda self, aid: {"id": aid},
        "list_disputes": lambda self, **k: {"items": [{"dispute_id": "D-1"}]},
        "search_transactions": lambda self, **k: {"transaction_details": []},
        "list_invoices": lambda self, **k: {"items": []},
    })()
    set_paypal_client_factory(lambda: spy)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    body = client.post(
        "/api/escales/captain/chat",
        json={"message": "List PayPal disputes for the treasurer"},
        headers={"x-admin-key": "n-admin", "Accept-Language": "fr-FR,fr;q=0.9"},
    ).json()
    assert body["model_source"] == "paypal_readonly_tools"
    assert "PayPal disputes" in body["reply"]
    assert "Litiges" not in body["reply"]


def test_n5_features_expose_public_crew_plan_id():
    async def run():
        await ensure_crew_supporter_catalog(NSpy())

    asyncio.run(run())
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    body = client.get("/api/escales/features").json()
    assert body.get("crew_supporter_plan_id") == "PLAN-N"


def test_reconcile_reports_searched_window():
    async def run():
        report = await reconcile_paypal_ledger(
            start_date="2099-06-01T00:00:00Z",
            end_date="2099-06-02T00:00:00Z",
            client=type("C", (), {"search_transactions": lambda self, **k: {"transaction_details": []}})(),
            finance_entries=[{
                "_id": "fin1",
                "kind": "pledge_captured",
                "capture_id": "CAP-1",
                "pledge_id": "p1",
                "amount_eur": "5.00",
                "at": "2026-11-04T10:00:00+00:00",
            }],
        )
        assert report["searched_start_date"] == report["start_date"]
        assert report["searched_end_date"] == report["end_date"]
        assert report["searched_start_date"] != report["requested_start_date"]

    asyncio.run(run())
