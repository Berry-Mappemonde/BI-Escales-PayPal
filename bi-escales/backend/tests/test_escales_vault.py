"""PayPal Vault pledges (setup token v3). Mock client only."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.departure_clock import run_departure_clock
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
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-04T08:00:00Z")
    reset_ledger()
    yield
    reset_ledger()


async def _seed_far_milestone(
    milestone_id: str = "dep-long-haul",
    *,
    departure_iso: str = "2027-05-15T08:00:00+00:00",
):
    await get_ledger().ensure_milestone(
        milestone_id,
        meta={
            "capture_on": "departure",
            "departure_iso": departure_iso,
            "arrival_iso": FAR_ARRIVAL,
            "title": "Long haul",
        },
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


def test_void_keeps_shared_vault_token_until_last_open_pledge(monkeypatch):
    monkeypatch.setenv("ESCALES_VAULT_ENABLED", "1")

    async def body():
        await _seed_far_milestone()
        await _seed_far_milestone("dep-share-b")
        client = VaultPayPal()
        first = await create_pledge(
            amount_eur="1.00",
            description="a",
            milestone_id="dep-long-haul",
            client=client,
            client_key="share-a",
        )
        await register_vault_pledge(first["_id"], client)
        first = await get_ledger().get_pledge(first["_id"])
        second = await create_pledge(
            amount_eur="2.00",
            description="b",
            milestone_id="dep-share-b",
            client=client,
            client_key="share-b",
        )
        await register_vault_pledge(second["_id"], client)
        second = await get_ledger().get_pledge(second["_id"])
        shared_vault = first["vault_id"]
        twin = await get_ledger().get_pledge(second["_id"])
        twin["vault_id"] = shared_vault
        await get_ledger().save_pledge(twin)

        void_first = await void_pledge(first["_id"], client)
        assert void_first["status"] == "voided"
        assert void_first["vault_token_deleted"] is False
        assert void_first.get("void_id") is None
        assert void_first["vault_voided_at"]
        assert not any(call[0] == "delete_token" for call in client.calls)

        still = await get_ledger().get_pledge(second["_id"])
        assert still["status"] == "vaulted"
        captured = await capture_pledge(second["_id"], client)
        assert captured["status"] == "captured"

        client.calls.clear()
        solo_a = await create_pledge(
            amount_eur="5.00",
            description="e",
            milestone_id="dep-long-haul",
            client=client,
            client_key="share-e",
        )
        await register_vault_pledge(solo_a["_id"], client)
        solo_a = await get_ledger().get_pledge(solo_a["_id"])
        solo_b = await create_pledge(
            amount_eur="6.00",
            description="f",
            milestone_id="dep-share-b",
            client=client,
            client_key="share-f",
        )
        await register_vault_pledge(solo_b["_id"], client)
        solo_b = await get_ledger().get_pledge(solo_b["_id"])
        shared2 = solo_a["vault_id"]
        twin = await get_ledger().get_pledge(solo_b["_id"])
        twin["vault_id"] = shared2
        await get_ledger().save_pledge(twin)

        void_a = await void_pledge(solo_a["_id"], client)
        assert void_a["vault_token_deleted"] is False
        assert not any(call[0] == "delete_token" for call in client.calls)

        void_b = await void_pledge(solo_b["_id"], client)
        assert void_b["vault_token_deleted"] is True
        assert ("delete_token", shared2) in client.calls

    asyncio.run(body())


def test_vault_void_records_token_deleted_not_void_id(monkeypatch):
    monkeypatch.setenv("ESCALES_VAULT_ENABLED", "1")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-03-01T09:00:00Z")

    async def body():
        await _seed_far_milestone()
        client = VaultPayPal()
        created = await create_pledge(
            amount_eur="1.00",
            description="solo",
            milestone_id="dep-long-haul",
            client=client,
            client_key="solo-v",
        )
        await register_vault_pledge(created["_id"], client)
        vaulted = await get_ledger().get_pledge(created["_id"])
        voided = await void_pledge(created["_id"], client)
        assert voided["vault_token_deleted"] is True
        assert voided.get("void_id") is None
        assert voided["vault_voided_at"].startswith("2026-03-01")
        assert ("delete_token", vaulted["vault_id"]) in client.calls

    asyncio.run(body())


def test_departure_clock_retries_vault_token_delete(monkeypatch):
    monkeypatch.setenv("ESCALES_VAULT_ENABLED", "1")

    class FlakyDelete:
        def __init__(self) -> None:
            self.calls: list[tuple] = []
            self.fail_delete = True

        def delete_payment_token(self, vault_id: str) -> dict:
            self.calls.append(("delete_token", vault_id))
            if self.fail_delete:
                from app.escales.paypal_client import PayPalError

                raise PayPalError(502, {"name": "INTERNAL_SERVER_ERROR", "debug_id": "del-1"})
            return {}

    async def body():
        from app.escales.milestones import record_evidence

        fake = FlakyDelete()
        await get_ledger().ensure_milestone(
            "dep-del-retry",
            meta={"capture_on": "departure", "departure_iso": "2026-12-01T08:00:00+00:00"},
        )
        row = {
            "_id": "vault-del",
            "status": "vaulted",
            "intent": "VAULT",
            "payment_mode": "VAULT",
            "vault_id": "VAULT-RETRY",
            "milestone_id": "dep-del-retry",
            "amount_eur": "10.00",
            "currency": "EUR",
            "kind": "mile",
            "target_id": "dep-del-retry",
            "history": ["vaulted"],
        }
        await get_ledger().insert_pledge_once(row)
        await record_evidence("dep-del-retry", met=False, facts={"cancelled": True})

        first = await run_departure_clock(fake)
        assert any(
            act["pledge_id"] == "vault-del" and act["action"] == "token_delete_pending"
            for act in first["actions"]
        )
        stored = await get_ledger().get_pledge("vault-del")
        assert stored["status"] == "token_delete_pending"

        fake.fail_delete = False
        second = await run_departure_clock(fake)
        assert any(
            act["pledge_id"] == "vault-del" and act["action"] == "void"
            for act in second["actions"]
        )
        done = await get_ledger().get_pledge("vault-del")
        assert done["status"] == "voided"
        assert done["vault_token_deleted"] is True
        assert ("delete_token", "VAULT-RETRY") in fake.calls

    asyncio.run(body())


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
