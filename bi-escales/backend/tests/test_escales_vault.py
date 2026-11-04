"""PayPal Vault pledges (setup token v3). Mock client only."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.ledger import get_ledger
from app.escales.pledges import (
    IllegalTransition,
    capture_pledge,
    create_pledge,
    register_vault_pledge,
    reset_ledger,
    sponsor_customer_id,
    void_pledge,
)
from app.routers.escales import router, set_paypal_client_factory

ADMIN = {"x-admin-key": "vault-admin"}
FAR_ARRIVAL = "2027-05-15T08:00:00+00:00"


def test_sponsor_customer_id_respects_paypal_max_length():
    long_label = "patron@" + ("x" * 120)
    named = sponsor_customer_id("abc" * 10, long_label)
    assert len(named) == 22
    assert named.startswith("s")
    anonymous = sponsor_customer_id("abcdef0123456789abcdef0123456789", None)
    assert len(anonymous) == 22
    assert anonymous.startswith("p")


class VaultPayPal:
    n = 0

    def __init__(self):
        self.calls = []

    def create_authorize_order(self, amount_eur, description, reference_id, idempotency_key=None):
        self.calls.append(("create_authorize", amount_eur))
        self.n += 1
        order_id = f"ORD{self.n}"
        return {
            "id": order_id,
            "links": [{"rel": "approve", "href": f"https://sandbox.paypal.com/checkoutnow?token={order_id}"}],
        }

    def create_setup_token(self, *args, **kwargs):
        self.calls.append(("setup_token", args, kwargs))
        self.n += 1
        token = f"SETUP{self.n}"
        return {
            "id": token,
            "links": [{"rel": "approve", "href": f"https://sandbox.paypal.com/agreements/approve?token={token}"}],
        }

    def get_setup_token(self, setup_token_id):
        self.calls.append(("get_setup_token", setup_token_id))
        return {"status": "APPROVED", "id": setup_token_id}

    def create_payment_token(self, setup_token_id, **kwargs):
        self.calls.append(("payment_token", setup_token_id, kwargs))
        return {"id": f"VAULT-{setup_token_id}"}

    def charge_vaulted(self, vault_id, amount_eur, reference_id, source="paypal", **kwargs):
        self.calls.append(("charge_vaulted", vault_id, amount_eur, reference_id, source))
        return {"id": "CAP-V", "status": "COMPLETED"}

    def delete_payment_token(self, vault_id):
        self.calls.append(("delete_token", vault_id))
        return {}

    def authorize_order(self, order_id, **kwargs):
        raise AssertionError("authorize_order should not run for vault pledges")

    def capture_authorization(self, authorization_id, final=True, **kwargs):
        self.calls.append(("capture_auth", authorization_id))

    def void_authorization(self, authorization_id, **kwargs):
        self.calls.append(("void_auth", authorization_id))


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_VAULT_ENABLED", "1")
    reset_ledger()
    yield
    reset_ledger()


async def _seed_far_milestone(milestone_id: str = "dep-long-haul"):
    await get_ledger().ensure_milestone(
        milestone_id,
        meta={"arrival_iso": FAR_ARRIVAL, "title": "Long haul"},
    )


def test_vault_pledge_lifecycle():
    async def body():
        await _seed_far_milestone()
        client = VaultPayPal()
        created = await create_pledge(
            amount_eur="25.00",
            description="25 milles",
            milestone_id="dep-long-haul",
            client=client,
            client_key="vault-a",
        )
        assert created["payment_mode"] == "VAULT"
        assert created["intent"] == "VAULT"
        assert created["status"] == "created"
        assert created["setup_token_id"] == "SETUP1"
        assert "agreements/approve" in created["approve_link"]
        assert client.calls[0][0] == "setup_token"

        vaulted = await register_vault_pledge(created["_id"], client)
        assert vaulted["status"] == "vaulted"
        assert vaulted["vault_id"] == "VAULT-SETUP1"

        captured = await capture_pledge(created["_id"], client)
        assert captured["status"] == "captured"
        assert ("charge_vaulted", "VAULT-SETUP1", "25.00", created["_id"], "paypal") in client.calls

        other_client = VaultPayPal()
        await _seed_far_milestone("dep-other")
        other = await create_pledge(
            amount_eur="1.00",
            description="1 mille",
            milestone_id="dep-other",
            client=other_client,
            client_key="vault-b",
        )
        await register_vault_pledge(other["_id"], other_client)
        voided = await void_pledge(other["_id"], other_client)
        assert voided["status"] == "voided"
        assert ("delete_token", "VAULT-SETUP1") in other_client.calls

    asyncio.run(body())


def test_card_token_is_charged_with_card_source():
    async def body():
        await _seed_far_milestone("dep-card")
        client = VaultPayPal()
        created = await create_pledge(
            amount_eur="1.00",
            description="carte",
            milestone_id="dep-card",
            client=client,
            client_key="vault-card",
        )

        def card_token(setup_token_id, **kwargs):
            client.calls.append(("payment_token", setup_token_id, kwargs))
            return {"id": "CARDTOK", "payment_source": {"card": {"last_digits": "1881"}}}

        client.create_payment_token = card_token
        vaulted = await register_vault_pledge(created["_id"], client)
        assert vaulted["vault_source"] == "card"
        assert vaulted["vault_id"] == "CARDTOK"
        captured = await capture_pledge(created["_id"], client)
        assert captured["status"] == "captured"
        assert ("charge_vaulted", "CARDTOK", "1.00", created["_id"], "card") in client.calls

    asyncio.run(body())


def test_vault_register_uses_the_stored_token_and_requires_approved():
    async def body():
        await _seed_far_milestone("dep-token")
        client = VaultPayPal()
        created = await create_pledge(
            amount_eur="1.00",
            description="jeton",
            milestone_id="dep-token",
            client=client,
            client_key="vault-token",
        )
        with pytest.raises(ValueError, match="does not match"):
            await register_vault_pledge(created["_id"], client, setup_token_id="OTHER")
        client.get_setup_token = lambda setup_token_id: {"status": "CREATED", "id": setup_token_id}
        with pytest.raises(ValueError, match="not approved"):
            await register_vault_pledge(created["_id"], client)
        client.get_setup_token = lambda setup_token_id: {"status": "APPROVED", "id": setup_token_id}
        vaulted = await register_vault_pledge(created["_id"], client)
        assert vaulted["status"] == "vaulted"
        assert vaulted["setup_token_id"] == created["setup_token_id"]
        assert any(
            call[0] == "payment_token" and call[1] == created["setup_token_id"] for call in client.calls
        )

    asyncio.run(body())


def test_vault_capture_forbidden_before_vaulted():
    async def body():
        await _seed_far_milestone()
        client = VaultPayPal()
        created = await create_pledge(
            amount_eur="1.00",
            description="x",
            milestone_id="dep-long-haul",
            client=client,
            client_key="vault-c",
        )
        with pytest.raises(IllegalTransition):
            await capture_pledge(created["_id"], client)

    asyncio.run(body())


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_VAULT_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "vault-admin")
    reset_ledger()
    fake = VaultPayPal()
    set_paypal_client_factory(lambda: fake)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client, fake
    set_paypal_client_factory(None)
    reset_ledger()


def test_http_vault_requires_admin_to_capture(api):
    client, fake = api
    asyncio.run(_seed_far_milestone())
    created = client.post(
        "/api/escales/pledges",
        json={"amount_eur": "10.00", "description": "10 milles", "milestone_id": "dep-long-haul"},
        headers={"PayPal-Request-Id": "http-vault-1"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["payment_mode"] == "VAULT"
    pledge_id = body["id"]
    vaulted = client.post(f"/api/escales/pledges/{pledge_id}/vault", json={})
    assert vaulted.status_code == 200
    assert vaulted.json()["status"] == "vaulted"
    denied = client.post(f"/api/escales/pledges/{pledge_id}/capture")
    assert denied.status_code == 401
    ok = client.post(f"/api/escales/pledges/{pledge_id}/capture", headers=ADMIN)
    assert ok.status_code == 200
    assert ok.json()["status"] == "captured"
    assert any(call[0] == "charge_vaulted" for call in fake.calls)


def test_vault_route_hidden_when_flag_off(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.delenv("ESCALES_VAULT_ENABLED", raising=False)
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "vault-admin")
    reset_ledger()
    fake = VaultPayPal()
    set_paypal_client_factory(lambda: fake)
    app = FastAPI()
    app.include_router(router)
    try:
        with TestClient(app) as client:
            flags = client.get("/api/escales/features").json()
            assert flags["vault"] is False
            response = client.post("/api/escales/pledges/p1/vault", json={})
            assert response.status_code == 404
    finally:
        set_paypal_client_factory(None)
        reset_ledger()
