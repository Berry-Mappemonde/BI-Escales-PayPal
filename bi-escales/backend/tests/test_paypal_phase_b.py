"""Phase B (7488f15): payouts, reconcile matching, subscription sale guard, capture timestamps."""
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
from app.escales.paypal_client import PayPalError
from app.escales.paypal_reconcile import reconcile_paypal_ledger
from app.escales.paypal_subscriptions import list_subscriptions_local
from app.escales.pledges import get_ledger, reset_ledger
from app.escales.project_payouts import approve_project_payout, find_payout_proposal, propose_project_payout
from app.escales.webhooks import verify_and_process
from app.routers.escales import router, set_paypal_client_factory


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "phase-b-admin")
    monkeypatch.setenv("ESCALES_VAULT_ENABLED", "0")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "wh-phase-b")
    reset_ledger()
    yield
    reset_ledger()
    set_paypal_client_factory(None)


ADMIN = {"x-admin-key": "phase-b-admin"}


def _webhook_headers(transmission_id: str) -> dict:
    return {
        "PAYPAL-TRANSMISSION-ID": transmission_id,
        "PAYPAL-TRANSMISSION-TIME": "2026-11-04T12:00:00Z",
        "PAYPAL-TRANSMISSION-SIG": "c2lnbmF0dXJl",
        "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT",
        "PAYPAL-AUTH-ALGO": "SHA256withRSA",
    }


def test_p1_payout_approve_failed_state_surfaces_paypal_error_and_409_retry():
    async def run():
        await get_ledger().save_pledge({
            "_id": "p1",
            "kind": "project_pledge",
            "target_id": "proj-p1",
            "status": "captured",
            "amount_eur": "20.00",
            "capture_id": "C1",
            "history": [],
        })
        proposal = await propose_project_payout(
            "proj-p1",
            amount_eur="5.00",
            receiver_email="payee@example.com",
        )

        class FailPayout:
            def create_payout(self, **kwargs):
                assert kwargs["amount_eur"] == "5.00"
                assert kwargs["receiver_email"] == "payee@example.com"
                raise PayPalError(400, {
                    "name": "VALIDATION_ERROR",
                    "debug_id": "dbg-payout-1",
                    "details": [{"issue": "INSUFFICIENT_FUNDS"}],
                })

        with pytest.raises(PayPalError):
            await approve_project_payout(proposal["_id"], FailPayout())
        failed = await find_payout_proposal(proposal["_id"])
        assert failed["status"] == "failed"
        assert failed["paypal_error"]["debug_id"] == "dbg-payout-1"
        with pytest.raises(Exception) as exc:
            await approve_project_payout(proposal["_id"], FailPayout())
        assert "failed" in str(exc.value).lower()

    asyncio.run(run())

    class RouteFailPayout:
        def create_payout(self, **kwargs):
            raise PayPalError(400, {
                "name": "VALIDATION_ERROR",
                "debug_id": "dbg-route",
                "details": [],
            })

    set_paypal_client_factory(lambda: RouteFailPayout())
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    async def seed():
        await get_ledger().save_pledge({
            "_id": "p2",
            "kind": "project_pledge",
            "target_id": "proj-route",
            "status": "captured",
            "amount_eur": "30.00",
            "capture_id": "C2",
            "history": [],
        })
        return await propose_project_payout("proj-route", amount_eur="3.00", receiver_email="a@example.com")

    prop = asyncio.run(seed())
    first = client.post(f"/api/escales/payouts/{prop['_id']}/approve", headers=ADMIN)
    assert first.status_code == 400
    detail_raw = first.json()["detail"]
    detail = json.loads(detail_raw) if str(detail_raw).startswith("{") else detail_raw
    if isinstance(detail, dict):
        assert detail.get("debug_id") == "dbg-route"
    retry = client.post(f"/api/escales/payouts/{prop['_id']}/approve", headers=ADMIN)
    assert retry.status_code == 409


def test_p2_reconcile_matches_by_capture_id_ignoring_simulated_finance_at():
    async def run():
        class TxnClient:
            def search_transactions(self, **kwargs):
                return {
                    "transaction_details": [{
                        "transaction_info": {
                            "transaction_id": "CAP-PHASE-B",
                            "transaction_amount": {"value": "7.00"},
                        },
                    }],
                }

        report = await reconcile_paypal_ledger(
            start_date="2026-11-04T00:00:00Z",
            end_date="2026-11-05T00:00:00Z",
            client=TxnClient(),
            finance_entries=[{
                "_id": "fin-old",
                "kind": "pledge_captured",
                "capture_id": "CAP-PHASE-B",
                "pledge_id": "pledge-b",
                "amount_eur": "7.00",
                "at": "1999-01-01T00:00:00+00:00",
            }],
        )
        assert len(report["matched"]) == 1
        assert report["matched"][0]["capture_id"] == "CAP-PHASE-B"
        assert report["matched"][0]["amounts_match"] is True

    asyncio.run(run())


def test_p3_payment_sale_without_billing_agreement_does_not_create_subscription_row():
    async def run():
        class WSpy:
            def verify_webhook_signature(self, **kwargs):
                return {"verification_status": "SUCCESS"}

        sale = {
            "id": "evt-sale-orphan",
            "event_type": "PAYMENT.SALE.COMPLETED",
            "resource": {
                "id": "2PF123456789",
                "state": "completed",
            },
        }
        await verify_and_process(
            raw_body=json.dumps(sale).encode(),
            headers=_webhook_headers("tx-sale-orphan"),
            client=WSpy(),
        )
        rows = await list_subscriptions_local()
        assert rows == []

    asyncio.run(run())


def test_p4_manual_capture_finance_at_matches_pinned_capture_timestamp(monkeypatch):
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-01T10:15:00+00:00")

    class MoneySpy:
        def capture_authorization(self, auth_id, **k):
            return {
                "id": auth_id,
                "status": "COMPLETED",
                "purchase_units": [{
                    "payments": {"captures": [{"id": "CAP-P4", "status": "COMPLETED"}]},
                }],
            }

    set_paypal_client_factory(lambda: MoneySpy())
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    async def seed():
        await get_ledger().save_pledge({
            "_id": "pledge-p4",
            "kind": "mile",
            "milestone_id": "dep-la-rochelle",
            "status": "authorized",
            "amount_eur": "4.00",
            "currency": "EUR",
            "authorization_id": "AUTH-P4",
            "authorized_at": "2027-06-01T09:00:00+00:00",
            "history": ["authorized"],
        })
        return "pledge-p4"

    pledge_id = asyncio.run(seed())
    captured = client.post(
        f"/api/escales/pledges/{pledge_id}/capture",
        json={"now": "2027-06-01T10:15:00+00:00"},
        headers=ADMIN,
    )
    assert captured.status_code == 200
    body = captured.json()
    assert body["captured_at"].startswith("2027-06-01")

    async def finance_at():
        for entry in await list_finance_entries():
            if entry.get("kind") == "pledge_captured" and entry.get("pledge_id") == pledge_id:
                return entry.get("at")
        return None

    assert asyncio.run(finance_at()) == body["captured_at"]
