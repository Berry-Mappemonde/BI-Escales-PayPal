"""P1 PayPal full audit: honor reauth, refund, payout, reconcile, mock header, chat tools."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.config import EscalesConfig
from app.escales.paypal_client import PayPalClient, PayPalError
from app.escales.paypal_reconcile import reconcile_paypal_ledger
from app.escales.pledges import (
    authorize_pledge,
    capture_pledge,
    create_pledge,
    get_ledger,
    refund_pledge,
    reset_ledger,
)
from app.escales.project_payouts import approve_project_payout, propose_project_payout
from app.routers.escales import router, set_paypal_client_factory


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "audit-admin")
    reset_ledger()
    yield
    reset_ledger()
    set_paypal_client_factory(None)


class AuditSpy:
    def __init__(self):
        self.calls = []
        self.n = 0

    def create_authorize_order(self, *args, **kwargs):
        self.n += 1
        oid = f"O{self.n}"
        self.calls.append(("create", oid))
        return {
            "id": oid,
            "links": [{"rel": "approve", "href": f"https://sandbox.paypal.com/checkoutnow?token={oid}"}],
        }

    def authorize_order(self, order_id, **kwargs):
        self.calls.append(("authorize", order_id))
        return {
            "id": order_id,
            "purchase_units": [{
                "payments": {"authorizations": [{"id": f"A-{order_id}", "expiration_time": "2027-06-01T00:00:00Z"}]},
            }],
        }

    def reauthorize(self, authorization_id, **kwargs):
        self.calls.append(("reauthorize", authorization_id))
        return {"id": f"R-{authorization_id}", "expiration_time": "2027-07-01T00:00:00Z"}

    def capture_authorization(self, authorization_id, **kwargs):
        self.calls.append(("capture", authorization_id))
        return {"id": "CAP-AUDIT", "status": "COMPLETED"}

    def get_order(self, order_id):
        return {"id": order_id, "status": "APPROVED"}

    def get_authorization(self, authorization_id):
        return {"id": authorization_id, "status": "CREATED"}

    def list_invoices(self, **kwargs):
        return {"items": []}

    def refund_capture(self, capture_id, **kwargs):
        self.calls.append(("refund", capture_id))
        return {"id": "RF1", "status": "COMPLETED"}

    def search_transactions(self, *, start_date, end_date):
        self.calls.append(("search", start_date, end_date))
        return {"transaction_details": [{"transaction_info": {"transaction_id": "CAP-AUDIT", "transaction_amount": {"value": "5.00"}}}]}

    def create_payout(self, **kwargs):
        self.calls.append(("payout", kwargs.get("batch_id")))
        return {"batch_header": {"payout_batch_id": "BATCH1"}}

    def list_disputes(self, **kwargs):
        return {"items": []}


def test_mock_response_header_is_sent(monkeypatch):
    seen = []

    def handler(request: httpx.Request):
        seen.append(request.headers.get("PayPal-Mock-Response"))
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        if request.url.path == "/v2/checkout/orders" and seen[-1]:
            return httpx.Response(500, json={"name": "INTERNAL_SERVER_ERROR", "debug_id": "mock-1"})
        return httpx.Response(201, json={"id": "X"})

    client = PayPalClient(
        EscalesConfig("cid", "secret"),
        transport=httpx.MockTransport(handler),
    )
    client.mock_response = '{"mock_application_codes":"INTERNAL_SERVER_ERROR"}'
    with pytest.raises(PayPalError):
        client.create_authorize_order("1.00", "miles", "p-mock")
    assert seen[-1] == '{"mock_application_codes":"INTERNAL_SERVER_ERROR"}'


def test_reauthorize_after_honor_period(monkeypatch):
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-05-15T08:00:00Z")

    async def run():
        spy = AuditSpy()
        created = await create_pledge(
            amount_eur="5.00",
            description="miles",
            milestone_id="dep-mayotte",
            client=spy,
            client_key="honor-key",
        )
        await authorize_pledge(created["_id"], spy)
        pledge = await get_ledger().get_pledge(created["_id"])
        pledge["authorized_at"] = "2026-11-06T12:00:00+00:00"
        await get_ledger().save_pledge(pledge)
        captured = await capture_pledge(created["_id"], spy)
        assert ("reauthorize", f"A-{created['order_id']}") in spy.calls
        assert captured["status"] == "captured"
        assert captured["capture_id"] == "CAP-AUDIT"

    asyncio.run(run())


def test_refund_captured_pledge(monkeypatch):
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-05-15T08:00:00Z")

    async def run():
        spy = AuditSpy()
        created = await create_pledge(
            amount_eur="5.00",
            description="miles",
            milestone_id="dep-mayotte",
            client=spy,
            client_key="rf",
        )
        await authorize_pledge(created["_id"], spy)
        await capture_pledge(created["_id"], spy)
        refunded = await refund_pledge(created["_id"], spy)
        assert refunded["status"] == "refunded"
        assert ("refund", "CAP-AUDIT") in spy.calls

    asyncio.run(run())


def test_payout_requires_approval_before_paypal():
    async def run():
        await get_ledger().save_pledge({
            "_id": "proj-pledge-1",
            "kind": "project_pledge",
            "target_id": "proj-1",
            "status": "captured",
            "amount_eur": "20.00",
            "capture_id": "CAP-P1",
            "history": [],
        })
        proposal = await propose_project_payout(
            "proj-1",
            amount_eur="12.50",
            receiver_email="sandbox@example.com",
            note="grant",
        )
        assert proposal["status"] == "pending_approval"
        spy = AuditSpy()
        sent = await approve_project_payout(proposal["_id"], spy)
        assert sent["status"] == "sent"
        assert ("payout", f"payout-{proposal['_id']}") in spy.calls

    asyncio.run(run())


def test_reconcile_ledger_and_paypal():
    async def run():
        spy = AuditSpy()
        entries = [{
            "_id": "fin1",
            "kind": "pledge_captured",
            "capture_id": "CAP-AUDIT",
            "pledge_id": "p1",
            "amount_eur": "5.00",
            "at": "2026-11-04T10:00:00+00:00",
        }]
        report = await reconcile_paypal_ledger(
            start_date="2026-11-01T00:00:00Z",
            end_date="2026-11-30T23:59:59Z",
            client=spy,
            finance_entries=entries,
        )
        assert report["ledger_capture_count"] == 1
        assert report["matched"][0]["capture_id"] == "CAP-AUDIT"

    asyncio.run(run())


def test_treasurer_chat_exposes_readonly_paypal_tools():
    spy = AuditSpy()
    set_paypal_client_factory(lambda: spy)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    denied = client.post(
        "/api/escales/captain/chat",
        json={"message": "List PayPal transactions", "lang": "en"},
    )
    assert "read-only" not in denied.json()["reply"].lower()
    ok = client.post(
        "/api/escales/captain/chat",
        json={"message": "List PayPal transactions for the treasurer", "lang": "en"},
        headers={"x-admin-key": "audit-admin"},
    )
    body = ok.json()
    assert body["model_source"] == "paypal_readonly_tools"
    assert "transactions.search" in body.get("paypal_tools", [])
    assert "read-only" in body["reply"].lower()
    assert any(call[0] == "search" for call in spy.calls)


def test_admin_refund_route(api, monkeypatch):
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-05-15T08:00:00Z")
    spy = AuditSpy()
    set_paypal_client_factory(lambda: spy)
    created = api.post(
        "/api/escales/pledges",
        json={"amount_eur": "5.00", "description": "miles", "milestone_id": "dep-mayotte"},
    ).json()
    api.post(f"/api/escales/pledges/{created['id']}/authorize")
    api.post(
        f"/api/escales/pledges/{created['id']}/capture",
        headers={"x-admin-key": "audit-admin"},
    )
    refunded = api.post(
        f"/api/escales/pledges/{created['id']}/refund",
        headers={"x-admin-key": "audit-admin"},
        json={},
    )
    assert refunded.status_code == 200
    assert refunded.json()["status"] == "refunded"


@pytest.fixture
def api(monkeypatch):
    spy = AuditSpy()
    set_paypal_client_factory(lambda: spy)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)
