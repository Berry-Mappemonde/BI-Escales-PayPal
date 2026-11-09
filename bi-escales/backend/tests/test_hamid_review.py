"""Hamid review: refund idempotency, capture retries, trusted proxy client IP."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.paypal_client import PayPalError
from app.escales.pledges import (
    authorize_pledge,
    capture_pledge,
    create_pledge,
    get_ledger,
    reconcile_refund_on_pledge,
    refund_pledge,
    refunded_amount_from_pledge,
    reset_ledger,
)
from app.escales.rate_limit import client_ip, trusted_proxy_hops


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-05-15T08:00:00Z")
    reset_ledger()
    yield
    reset_ledger()


class RecordingPayPal:
    """Records PayPal-Request-Id values passed as idempotency_key."""

    def __init__(self):
        self.refund_keys: list[str] = []
        self.capture_keys: list[str] = []
        self.vault_keys: list[str] = []
        self.refund_n = 0
        self.capture_n = 0
        self.vault_n = 0
        self.transport_once = False
        self.force_capture_ok = False

    def create_authorize_order(self, amount_eur, description, reference_id, idempotency_key=None):
        return {
            "id": "ORD-H",
            "status": "CREATED",
            "intent": "AUTHORIZE",
            "links": [{"rel": "approve", "href": "https://sandbox.paypal.com/checkoutnow?token=ORD-H"}],
        }

    def authorize_order(self, order_id, **kwargs):
        return {
            "id": order_id,
            "purchase_units": [{
                "payments": {
                    "authorizations": [{
                        "id": "AUTH-H",
                        "expiration_time": "2099-01-01T00:00:00Z",
                    }],
                },
            }],
        }

    def capture_authorization(self, authorization_id, final=True, *, idempotency_key=None, **kwargs):
        self.capture_keys.append(str(idempotency_key or ""))
        self.capture_n += 1
        if self.transport_once and self.capture_n == 1:
            raise httpx.TimeoutException("retry me")
        if self.force_capture_ok or self.capture_n > 1:
            return {"id": "CAP-OK", "status": "COMPLETED"}
        return {"id": "CAP-DECL", "status": "DECLINED"}

    def refund_capture(self, capture_id, *, amount_eur=None, idempotency_key=None, **kwargs):
        self.refund_keys.append(str(idempotency_key or ""))
        self.refund_n += 1
        return {"id": f"REF-{self.refund_n}", "status": "COMPLETED"}

    def get_order(self, order_id):
        return {"id": order_id, "status": "APPROVED"}

    def reauthorize(self, authorization_id, **kwargs):
        return {
            "id": authorization_id,
            "expiration_time": "2099-01-01T00:00:00Z",
        }

    def create_setup_token(self, return_url, cancel_url, **kwargs):
        return {
            "id": "SETUP-H",
            "status": "CREATED",
            "links": [{"rel": "approve", "href": "https://sandbox.paypal.com/vault/setup"}],
        }

    def create_payment_token(self, setup_token_id, **kwargs):
        return {"id": "VAULT-H", "payment_source": {"paypal": {}}}

    def get_setup_token(self, setup_token_id):
        return {"id": setup_token_id, "status": "APPROVED", "customer": {"id": "cust"}}

    def charge_vaulted(
        self,
        vault_id,
        amount_eur,
        reference_id,
        source="paypal",
        *,
        description="",
        idempotency_key=None,
        **kwargs,
    ):
        self.vault_keys.append(str(idempotency_key or ""))
        self.vault_n += 1
        if self.transport_once and self.vault_n == 1:
            raise PayPalError(502, body=None)
        if self.vault_n == 1:
            return {
                "id": "ORD-V",
                "status": "COMPLETED",
                "purchase_units": [{
                    "payments": {
                        "captures": [{"id": "CAP-V-DECL", "status": "DECLINED"}],
                    },
                }],
            }
        return {
            "id": "ORD-V2",
            "status": "COMPLETED",
            "purchase_units": [{
                "payments": {
                    "captures": [{"id": "CAP-V-OK", "status": "COMPLETED"}],
                },
            }],
        }

    def delete_payment_token(self, vault_id):
        return {}


async def _authorized_pledge(client: RecordingPayPal, monkeypatch):
    created = await create_pledge(
        amount_eur="10.00",
        description="hamid",
        milestone_id="dep-mayotte",
        client=client,
        client_key="hamid",
    )
    await authorize_pledge(created["_id"], client)
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-12T08:00:00Z")
    pledge = await get_ledger().get_pledge(created["_id"])
    assert pledge is not None
    pledge["authorized_at"] = "2027-06-11T08:00:00+00:00"
    await get_ledger().save_pledge(pledge)
    return created["_id"]


async def _captured_pledge(client: RecordingPayPal, monkeypatch):
    client.force_capture_ok = True
    pledge_id = await _authorized_pledge(client, monkeypatch)
    captured = await capture_pledge(pledge_id, client)
    assert captured["status"] == "captured"
    return pledge_id


def test_two_partial_refunds_use_distinct_idempotency_keys(monkeypatch):
    async def run():
        client = RecordingPayPal()
        pledge_id = await _captured_pledge(client, monkeypatch)
        await refund_pledge(pledge_id, client, amount_eur="3.00")
        await refund_pledge(pledge_id, client, amount_eur="2.00")
        assert len(client.refund_keys) == 2
        assert client.refund_keys[0] != client.refund_keys[1]
        assert client.refund_keys[0] == f"refund-{pledge_id}-3.00"
        assert client.refund_keys[1] == f"refund-{pledge_id}-2.00"

    asyncio.run(run())


def test_replayed_refund_id_is_not_double_counted(monkeypatch):
    async def run():
        pledge_id = await _captured_pledge(RecordingPayPal(), monkeypatch)
        pledge = await get_ledger().get_pledge(pledge_id)
        assert pledge is not None
        await reconcile_refund_on_pledge(
            pledge,
            refund_id="REF-DUP",
            amount_eur="4.00",
            status="COMPLETED",
        )
        pledge = await get_ledger().get_pledge(pledge_id)
        assert pledge is not None
        await reconcile_refund_on_pledge(
            pledge,
            refund_id="REF-DUP",
            amount_eur="4.00",
            status="COMPLETED",
        )
        pledge = await get_ledger().get_pledge(pledge_id)
        assert pledge is not None
        assert len(pledge.get("refunds") or []) == 1
        assert refunded_amount_from_pledge(pledge) == pytest.approx(4.0)

    asyncio.run(run())


def test_declined_capture_then_retry_sends_new_idempotency_key(monkeypatch):
    async def run():
        client = RecordingPayPal()
        pledge_id = await _authorized_pledge(client, monkeypatch)
        with pytest.raises(ValueError, match="not COMPLETED or PENDING"):
            await capture_pledge(pledge_id, client)
        assert len(client.capture_keys) == 1
        captured = await capture_pledge(pledge_id, client)
        assert captured["status"] == "captured"
        assert len(client.capture_keys) == 2
        assert client.capture_keys[0] != client.capture_keys[1]
        assert client.capture_keys[0] == f"capture-{pledge_id}-1"
        assert client.capture_keys[1] == f"capture-{pledge_id}-2"

    asyncio.run(run())


def test_transport_retry_reuses_capture_idempotency_key(monkeypatch):
    async def run():
        client = RecordingPayPal()
        client.transport_once = True
        pledge_id = await _authorized_pledge(client, monkeypatch)
        with pytest.raises(httpx.TimeoutException):
            await capture_pledge(pledge_id, client)
        assert client.capture_keys == [f"capture-{pledge_id}-1"]
        captured = await capture_pledge(pledge_id, client)
        assert captured["status"] == "captured"
        assert client.capture_keys[0] == client.capture_keys[1]

    asyncio.run(run())


def test_vault_charge_declined_then_retry_and_transport(monkeypatch):
    monkeypatch.setenv("ESCALES_VAULT_ENABLED", "1")

    async def run():
        client = RecordingPayPal()
        created = await create_pledge(
            amount_eur="8.00",
            description="vault hamid",
            milestone_id="dep-mayotte",
            client=client,
            client_key="vault-h",
            payment_mode="VAULT",
        )
        created["vault_id"] = "VAULT-H"
        created["status"] = "vaulted"
        created["history"] = list(created.get("history") or []) + ["vaulted"]
        await get_ledger().save_pledge(created)
        monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-12T08:00:00Z")
        with pytest.raises(ValueError, match="not COMPLETED or PENDING"):
            await capture_pledge(created["_id"], client)
        assert client.vault_keys == [f"capture-{created['_id']}-1"]
        captured = await capture_pledge(created["_id"], client)
        assert captured["status"] == "captured"
        assert client.vault_keys[1] == f"capture-{created['_id']}-2"

        client.transport_once = True
        client.vault_n = 0
        client.vault_keys.clear()
        created2 = await create_pledge(
            amount_eur="6.00",
            description="vault transport",
            milestone_id="dep-brest",
            client=client,
            client_key="vault-t",
            payment_mode="VAULT",
        )
        created2["vault_id"] = "VAULT-T"
        created2["status"] = "vaulted"
        created2["history"] = list(created2.get("history") or []) + ["vaulted"]
        await get_ledger().save_pledge(created2)
        monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-12T08:00:00Z")
        with pytest.raises(PayPalError):
            await capture_pledge(created2["_id"], client)
        assert client.vault_keys == [f"capture-{created2['_id']}-1"]
        ok = await capture_pledge(created2["_id"], client)
        assert ok["status"] == "captured"
        assert client.vault_keys[0] == client.vault_keys[1]

    asyncio.run(run())


def test_client_ip_trusted_proxy_hops(monkeypatch):
    monkeypatch.setenv("ESCALES_TRUSTED_PROXY_HOPS", "1")
    assert trusted_proxy_hops() == 1
    assert client_ip("1.1.1.1, 9.9.9.9", "127.0.0.1") == "9.9.9.9"
    assert client_ip("203.0.113.1, 1.1.1.1, 9.9.9.9", "127.0.0.1") == "9.9.9.9"
    assert client_ip("", "10.0.0.5") == "10.0.0.5"
    monkeypatch.setenv("ESCALES_TRUSTED_PROXY_HOPS", "0")
    assert client_ip("1.1.1.1, 9.9.9.9", "10.0.0.5") == "10.0.0.5"
