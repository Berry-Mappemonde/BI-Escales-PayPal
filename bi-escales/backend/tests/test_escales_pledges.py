"""Pledge state machine and the PayPal AUTHORIZE client. No network."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.config import EscalesConfig, load_config
from app.escales.paypal_client import PayPalClient, approve_link
from app.escales.pledges import (
    COLLECTIONS,
    IllegalTransition,
    authorize_pledge,
    capture_pledge,
    create_pledge,
    reset_ledger,
    void_pledge,
)
from tests.near_horizon import seed_near


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    reset_ledger()
    asyncio.run(seed_near())
    yield
    reset_ledger()


class Spy:
    def __init__(self):
        self.calls = []
        self.n = 0

    def create_authorize_order(self, amount_eur, description, reference_id, idempotency_key=None):
        self.calls.append(("create", amount_eur, idempotency_key))
        self.n += 1
        order_id = f"ORDER{self.n}"
        return {
            "id": order_id,
            "status": "CREATED",
            "intent": "AUTHORIZE",
            "links": [{
                "rel": "approve",
                "href": f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}",
            }],
        }

    def authorize_order(self, order_id):
        self.calls.append(("authorize", order_id))
        return {
            "id": order_id,
            "purchase_units": [{
                "payments": {
                    "authorizations": [{
                        "id": f"AUTH-{order_id}",
                        "expiration_time": "2026-12-01T00:00:00Z",
                    }],
                },
            }],
        }

    def capture_authorization(self, authorization_id, final=True):
        self.calls.append(("capture", authorization_id))
        return {"id": "CAP", "status": "COMPLETED"}

    def void_authorization(self, authorization_id):
        self.calls.append(("void", authorization_id))
        return {}

    def get_order(self, order_id):
        self.calls.append(("orders.get", order_id))
        return {"id": order_id, "status": "APPROVED"}

    def get_authorization(self, authorization_id):
        self.calls.append(("authorizations.get", authorization_id))
        return {"id": authorization_id, "status": "CREATED"}


def _names(spy: Spy) -> list[str]:
    return [call[0] for call in spy.calls]


def test_create_authorize_order_is_eur_and_idempotent():
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.method, request.url.path, request.headers.get("PayPal-Request-Id"), request.content))
        path = request.url.path
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        if path == "/v2/checkout/orders" and request.method == "POST":
            body = json.loads(request.content)
            assert body["intent"] == "AUTHORIZE"
            assert body["purchase_units"][0]["amount"] == {"currency_code": "EUR", "value": "20.00"}
            return httpx.Response(201, json={
                "id": "ORDER1",
                "status": "CREATED",
                "intent": "AUTHORIZE",
                "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1"}],
            })
        if path == "/v2/checkout/orders/ORDER1/authorize":
            return httpx.Response(201, json={
                "id": "ORDER1",
                "purchase_units": [{
                    "payments": {"authorizations": [{"id": "AUTH1", "expiration_time": "2026-12-01T00:00:00Z"}]},
                }],
            })
        if path == "/v2/checkout/orders/ORDER1" and request.method == "GET":
            return httpx.Response(200, json={"id": "ORDER1", "status": "APPROVED"})
        if path == "/v2/payments/authorizations/AUTH1" and request.method == "GET":
            return httpx.Response(200, json={"id": "AUTH1", "status": "CREATED"})
        if path == "/v2/payments/authorizations/AUTH1/void":
            return httpx.Response(204)
        return httpx.Response(404, json={"name": "NOT_FOUND"})

    client = PayPalClient(
        EscalesConfig("test-client-id", "test-client-secret"),
        transport=httpx.MockTransport(handler),
    )
    order = client.create_authorize_order("20.00", "Menu Berry-Mappemonde", "p1", idempotency_key="pledge-key-1")
    assert order["id"] == "ORDER1"
    assert approve_link(order) == "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1"
    assert approve_link({"id": "ORDER9"}) == "https://www.sandbox.paypal.com/checkoutnow?token=ORDER9"
    client.authorize_order("ORDER1")
    assert client.get_order("ORDER1")["status"] == "APPROVED"
    assert client.get_authorization("AUTH1")["id"] == "AUTH1"
    assert client.void_authorization("AUTH1") == {}
    paths = [item[1] for item in seen]
    assert paths == [
        "/v1/oauth2/token",
        "/v2/checkout/orders",
        "/v2/checkout/orders/ORDER1/authorize",
        "/v2/checkout/orders/ORDER1",
        "/v2/payments/authorizations/AUTH1",
        "/v2/payments/authorizations/AUTH1/void",
    ]
    assert seen[1][2] == "pledge-key-1"
    assert all("capture" not in path for path in paths)


def test_non_sandbox_env_is_refused(monkeypatch):
    monkeypatch.setenv("PAYPAL_ENV", "live")
    with pytest.raises(RuntimeError):
        load_config()


def test_collections_are_namespaced():
    assert COLLECTIONS == (
        "escales_pledges",
        "escales_milestones",
        "escales_audit",
        "escales_finance",
        "escales_webhooks",
    )


def test_same_client_key_reuses_pledge_without_a_second_order():
    async def body():
        spy = Spy()
        first = await create_pledge(
            amount_eur="20.00",
            description="20 milles",
            milestone_id="dep-mayotte",
            client=spy,
            client_key="same-key",
        )
        second = await create_pledge(
            amount_eur="60.00",
            description="autre",
            milestone_id="other",
            client=spy,
            client_key="same-key",
        )
        assert first["_id"] == second["_id"]
        assert first["order_id"] == second["order_id"] == "ORDER1"
        assert first["amount_eur"] == "20.00"
        assert _names(spy) == ["create"]
        assert spy.calls[0][2] == "same-key"

    asyncio.run(body())


def test_state_machine_and_forbidden_transitions():
    async def body():
        spy = Spy()
        created = await create_pledge(
            amount_eur="20.00",
            description="20 milles",
            milestone_id="dep-mayotte",
            client=spy,
            client_key="pledge-a",
        )
        assert created["status"] == "created"
        assert created["intent"] == "AUTHORIZE"
        assert created["currency"] == "EUR"
        with pytest.raises(IllegalTransition):
            await capture_pledge(created["_id"], spy)
        with pytest.raises(IllegalTransition):
            await void_pledge(created["_id"], spy)

        authorized = await authorize_pledge(created["_id"], spy)
        assert authorized["status"] == "authorized"
        assert authorized["authorization_id"] == "AUTH-ORDER1"
        assert authorized["authorization_expires_at"] == "2026-12-01T00:00:00Z"
        with pytest.raises(IllegalTransition):
            await authorize_pledge(created["_id"], spy)

        captured = await capture_pledge(created["_id"], spy)
        assert captured["status"] == "captured"
        with pytest.raises(IllegalTransition):
            await void_pledge(created["_id"], spy)
        with pytest.raises(IllegalTransition):
            await capture_pledge(created["_id"], spy)

        other = await create_pledge(
            amount_eur="60.00",
            description="diner",
            milestone_id="dep-mayotte",
            client=spy,
            client_key="pledge-b",
        )
        await authorize_pledge(other["_id"], spy)
        voided = await void_pledge(other["_id"], spy)
        assert voided["status"] == "voided"
        with pytest.raises(IllegalTransition):
            await capture_pledge(other["_id"], spy)
        with pytest.raises(IllegalTransition):
            await void_pledge(other["_id"], spy)

        assert _names(spy).count("capture") == 1
        assert _names(spy).count("void") == 1
        assert "orders.get" not in _names(spy)

    asyncio.run(body())


@pytest.mark.live
def test_live_sandbox_create_authorize_order():
    """Optional sandbox create. Skipped unless PAYPAL_CLIENT_ID is set. Does not print secrets."""
    if not os.environ.get("PAYPAL_CLIENT_ID"):
        pytest.skip("PAYPAL_CLIENT_ID is not set")
    if not os.environ.get("PAYPAL_CLIENT_SECRET"):
        pytest.skip("PAYPAL_CLIENT_SECRET is not set")
    client = PayPalClient(load_config())
    order = client.create_authorize_order(
        "1.00",
        "BI Escales live probe",
        "live-probe",
        idempotency_key="escales-live-probe",
    )
    assert order.get("id")
    assert order.get("intent") == "AUTHORIZE"
    assert approve_link(order)
