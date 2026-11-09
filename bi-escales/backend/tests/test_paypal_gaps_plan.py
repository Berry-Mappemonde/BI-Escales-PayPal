"""Vault-on-purchase and TEST reauthorize routes."""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.pledges import admin_reauthorize_pledge, authorize_pledge, create_pledge, reset_ledger
from app.routers.escales import router, set_paypal_client_factory
from app.escales.webhooks import _AUDITED_EVENTS


class Spy:
    def __init__(self):
        self.calls: list[tuple] = []
        self.mock_response = None

    def create_authorize_order(self, **kwargs):
        self.calls.append(("wallet-order", kwargs))
        return {"id": "ORDER-W", "links": [{"rel": "approve", "href": "https://sandbox.paypal.com/w"}]}

    def create_authorize_vault_order(self, **kwargs):
        self.calls.append(("vault-order", kwargs))
        return {"id": "ORDER-V", "links": [{"rel": "approve", "href": "https://sandbox.paypal.com/v"}]}

    def get_order(self, order_id):
        return {"id": order_id, "status": "APPROVED"}

    def authorize_order(self, order_id, *, pledge_id=None):
        return {
            "id": order_id,
            "purchase_units": [
                {
                    "payments": {
                        "authorizations": [
                            {
                                "id": "AUTH-OLD",
                                "expiration_time": "2099-01-01T00:00:00Z",
                            }
                        ]
                    }
                }
            ],
        }

    def reauthorize(self, authorization_id, *, pledge_id=None):
        self.calls.append(("reauthorize", authorization_id))
        return {"id": "AUTH-NEW", "expiration_time": "2099-06-01T00:00:00Z"}


def test_vault_on_purchase_uses_vault_order(monkeypatch):
    monkeypatch.setenv("ESCALES_VAULT_ON_PURCHASE_ENABLED", "1")
    reset_ledger()

    async def noop(_draft):
        return None

    monkeypatch.setattr("app.escales.departure_clock.refuse_early_authorization", noop)

    async def body():
        spy = Spy()
        doc = await create_pledge(
            amount_eur="5.00",
            description="5 miles",
            milestone_id="dep-mayotte",
            client=spy,
        )
        assert spy.calls[0][0] == "vault-order"
        assert doc["order_id"] == "ORDER-V"
        assert doc.get("vault_on_purchase") is True

    asyncio.run(body())
    reset_ledger()


def test_admin_reauthorize_route_is_hidden_in_production(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin-key")
    monkeypatch.setenv("ESCALES_ENV", "production")
    reset_ledger()
    set_paypal_client_factory(lambda: Spy())
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        res = client.post(
            "/api/escales/admin/pledges/x/reauthorize",
            headers={"x-admin-key": "test-admin-key"},
        )
        assert res.status_code == 404
    set_paypal_client_factory(None)


def test_admin_reauthorize_calls_paypal(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin-key")
    monkeypatch.delenv("ESCALES_ENV", raising=False)
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-12T08:00:00Z")
    reset_ledger()
    spy = Spy()
    set_paypal_client_factory(lambda: spy)

    async def seed():
        async def noop(_draft):
            return None

        monkeypatch.setattr("app.escales.departure_clock.refuse_early_authorization", noop)
        created = await create_pledge(
            amount_eur="5.00",
            description="5 miles",
            milestone_id="dep-mayotte",
            client=spy,
        )
        from app.escales.config import simulated_now

        authorized = await authorize_pledge(created["_id"], spy)
        authorized["authorized_at"] = (
            simulated_now() - dt.timedelta(days=5)
        ).replace(microsecond=0).isoformat()
        from app.escales.ledger import get_ledger

        await get_ledger().save_pledge(authorized)
        return authorized["_id"]

    pledge_id = asyncio.run(seed())
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        res = client.post(
            f"/api/escales/admin/pledges/{pledge_id}/reauthorize",
            headers={"x-admin-key": "test-admin-key"},
            json={"mock_response": '{"mock_application_codes":"INTERNAL_SERVER_ERROR"}'},
        )
        assert res.status_code == 200, res.text
        assert "reauthorized" in res.json().get("history", [])
    assert any(call[0] == "reauthorize" for call in spy.calls)
    set_paypal_client_factory(None)
    reset_ledger()


def test_webhook_audit_list_includes_subscription_created_and_refunds():
    assert "BILLING.SUBSCRIPTION.CREATED" in _AUDITED_EVENTS
    assert "PAYMENT.CAPTURE.REVERSED" in _AUDITED_EVENTS
    assert "PAYMENT.REFUND.COMPLETED" in _AUDITED_EVENTS
