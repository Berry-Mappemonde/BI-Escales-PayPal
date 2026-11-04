"""Fix lot B3–B8 on PR #30: vault delete flag, GET txn search, payout cap, refunds, chat intent."""
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
from app.escales.pledges import capture_pledge, get_ledger, refund_pledge, reset_ledger
from app.escales.project_payouts import approve_project_payout, propose_project_payout
from app.routers.escales import router, set_paypal_client_factory


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "fix-admin")
    reset_ledger()
    yield
    reset_ledger()
    set_paypal_client_factory(None)


class VaultSpy:
    def __init__(self, *, delete_ok: bool = True):
        self.delete_ok = delete_ok
        self.calls = []

    def charge_vaulted(self, vault_id, amount_eur, reference_id, source="paypal", **kwargs):
        self.calls.append(("charge", vault_id))
        return {
            "id": "ORD-V1",
            "status": "COMPLETED",
            "intent": "CAPTURE",
            "purchase_units": [{
                "payments": {"captures": [{"id": "CAP-V1", "status": "COMPLETED"}]},
            }],
        }

    def delete_payment_token(self, vault_id):
        self.calls.append(("delete", vault_id))
        if not self.delete_ok:
            raise PayPalError(502, "delete failed")


def test_vault_capture_keeps_captured_when_token_delete_fails():
    async def run():
        spy = VaultSpy(delete_ok=False)
        ledger = get_ledger()
        pledge_id = "pv1"
        await ledger.save_pledge({
            "_id": pledge_id,
            "status": "vaulted",
            "payment_mode": "VAULT",
            "amount_eur": "10.00",
            "vault_id": "VTOK1",
            "vault_source": "paypal",
            "description": "test",
            "milestone_id": "dep-mayotte",
            "history": ["vaulted"],
        })
        saved = await capture_pledge(pledge_id, spy)
        assert saved["status"] == "captured"
        assert saved.get("vault_token_delete_pending") is True
        assert saved.get("capture_id") == "CAP-V1"

    asyncio.run(run())


def test_search_transactions_uses_get():
    paths = []

    def handler(request: httpx.Request):
        paths.append((request.method, request.url.path, str(request.url.query)))
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        return httpx.Response(200, json={"transaction_details": []})

    client = PayPalClient(
        EscalesConfig("cid", "secret"),
        transport=httpx.MockTransport(handler),
    )
    client.search_transactions(start_date="2026-01-01T00:00:00Z", end_date="2026-01-08T00:00:00Z")
    method, path, query = paths[-1]
    assert method == "GET"
    assert path == "/v1/reporting/transactions"
    assert "start_date=" in query


def test_payout_approve_is_idempotent():
    async def run():
        spy = type("P", (), {"create_payout": lambda *a, **k: {"batch_header": {"payout_batch_id": "B1"}}})()
        await get_ledger().save_pledge({
            "_id": "p1",
            "kind": "project_pledge",
            "target_id": "proj-x",
            "status": "captured",
            "amount_eur": "20.00",
            "capture_id": "C1",
            "history": [],
        })
        proposal = await propose_project_payout(
            "proj-x",
            amount_eur="5.00",
            receiver_email="a@example.com",
        )
        await approve_project_payout(proposal["_id"], spy)
        with pytest.raises(Exception) as exc:
            await approve_project_payout(proposal["_id"], spy)
        assert "already" in str(exc.value).lower()

    asyncio.run(run())


def test_payout_propose_respects_captured_cap():
    async def run():
        await get_ledger().save_pledge({
            "_id": "p1",
            "kind": "project_pledge",
            "target_id": "proj-y",
            "status": "captured",
            "amount_eur": "10.00",
            "capture_id": "C1",
            "history": [],
        })
        with pytest.raises(ValueError, match="exceeds"):
            await propose_project_payout(
                "proj-y",
                amount_eur="15.00",
                receiver_email="a@example.com",
            )

    asyncio.run(run())


def test_partial_refund_tracks_amount():
    async def run():
        class RSpy:
            def refund_capture(self, capture_id, **kwargs):
                return {"id": "RF1", "status": "COMPLETED"}

        await get_ledger().save_pledge({
            "_id": "r1",
            "status": "captured",
            "amount_eur": "10.00",
            "capture_id": "CAP-R1",
            "history": ["captured"],
        })
        saved = await refund_pledge("r1", RSpy(), amount_eur="4.00")
        assert saved["status"] == "partially_refunded"
        assert saved["refunded_amount_eur"] == "4.00"

    asyncio.run(run())


def test_checkout_locale_follows_app_language():
    bodies = []

    def handler(request: httpx.Request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"id": "O1", "links": []})

    client = PayPalClient(EscalesConfig("cid", "secret"), transport=httpx.MockTransport(handler))
    client.create_authorize_order("1.00", "miles", "p1", checkout_locale="en")
    locale = bodies[0]["payment_source"]["paypal"]["experience_context"]["locale"]
    assert locale == "en-US"


def test_captain_does_not_trigger_paypal_tools_on_casual_order_mention():
    spy = type("C", (), {
        "get_order": lambda self, oid: {"id": oid},
        "get_authorization": lambda self, aid: {"id": aid},
        "list_disputes": lambda self, **k: {"items": []},
        "search_transactions": lambda self, **k: {"transaction_details": []},
        "list_invoices": lambda self, **k: {"items": []},
    })()
    set_paypal_client_factory(lambda: spy)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    body = client.post(
        "/api/escales/captain/chat",
        json={"message": "I want to place an order for miles", "lang": "en"},
        headers={"x-admin-key": "fix-admin"},
    ).json()
    assert body.get("model_source") != "paypal_readonly_tools"


def test_captain_transactions_need_explicit_intent():
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
        json={"message": "List PayPal transactions for the treasurer", "lang": "en"},
        headers={"x-admin-key": "fix-admin"},
    ).json()
    assert body["model_source"] == "paypal_readonly_tools"
