"""C3 refund idempotency: webhook-first, duplicate API, partials, over-limit."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.pledges import (
    authorize_pledge,
    capture_pledge,
    create_pledge,
    get_ledger,
    reconcile_refund_on_pledge,
    refund_pledge,
    refunded_amount_from_pledge,
    reset_ledger,
    _normalize_refunds,
)


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-05-15T08:00:00Z")
    reset_ledger()
    yield
    reset_ledger()


class CountingPayPal:
    def __init__(self):
        self.refund_n = 0
        self.refund_keys: list[str] = []

    def create_authorize_order(self, amount_eur, description, reference_id, idempotency_key=None):
        return {
            "id": "ORD-C3",
            "status": "CREATED",
            "links": [{"rel": "approve", "href": "https://sandbox.paypal.com/checkoutnow?token=ORD-C3"}],
        }

    def authorize_order(self, order_id, **kwargs):
        return {
            "id": order_id,
            "purchase_units": [{
                "payments": {
                    "authorizations": [{"id": "AUTH-C3", "expiration_time": "2099-01-01T00:00:00Z"}],
                },
            }],
        }

    def capture_authorization(self, authorization_id, final=True, **kwargs):
        return {"id": "CAP-C3", "status": "COMPLETED"}

    def refund_capture(self, capture_id, *, amount_eur=None, idempotency_key=None, **kwargs):
        self.refund_keys.append(str(idempotency_key or ""))
        self.refund_n += 1
        return {"id": f"REF-C3-{self.refund_n}", "status": "COMPLETED"}

    def get_order(self, order_id):
        return {"id": order_id, "status": "APPROVED"}


async def _captured(client: CountingPayPal, monkeypatch):
    created = await create_pledge(
        amount_eur="10.00",
        description="c3 refund",
        milestone_id="dep-mayotte",
        client=client,
        client_key="c3-refund",
    )
    await authorize_pledge(created["_id"], client)
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-12T08:00:00Z")
    pledge = await get_ledger().get_pledge(created["_id"])
    assert pledge is not None
    pledge["authorized_at"] = "2027-06-11T08:00:00+00:00"
    await get_ledger().save_pledge(pledge)
    captured = await capture_pledge(created["_id"], client)
    assert captured["status"] == "captured"
    return created["_id"]


def test_webhook_refund_then_api_skips_paypal(monkeypatch):
    async def run():
        client = CountingPayPal()
        pledge_id = await _captured(client, monkeypatch)
        pledge = await get_ledger().get_pledge(pledge_id)
        assert pledge is not None
        await reconcile_refund_on_pledge(
            pledge,
            refund_id="REF-WH-C3",
            amount_eur="10.00",
            status="COMPLETED",
        )
        saved = await refund_pledge(pledge_id, client)
        assert client.refund_n == 0
        assert saved["status"] == "refunded"
        assert len(_normalize_refunds(saved)) == 1

    asyncio.run(run())


def test_duplicate_api_refund_one_paypal_call_and_one_row(monkeypatch):
    async def run():
        client = CountingPayPal()
        pledge_id = await _captured(client, monkeypatch)
        first = await refund_pledge(pledge_id, client, amount_eur="5.00")
        second = await refund_pledge(pledge_id, client, amount_eur="5.00")
        assert client.refund_n == 1
        assert client.refund_keys[0] == client.refund_keys[-1] == f"refund-{pledge_id}-5.00"
        assert len(_normalize_refunds(second)) == 1
        assert first["refunds"][0]["id"] == second["refunds"][0]["id"]

    asyncio.run(run())


def test_two_partial_refunds_within_remaining_both_succeed(monkeypatch):
    async def run():
        client = CountingPayPal()
        pledge_id = await _captured(client, monkeypatch)
        await refund_pledge(pledge_id, client, amount_eur="3.00")
        await refund_pledge(pledge_id, client, amount_eur="2.00")
        assert client.refund_n == 2
        assert client.refund_keys[0] == f"refund-{pledge_id}-3.00"
        assert client.refund_keys[1] == f"refund-{pledge_id}-2.00"
        pledge = await get_ledger().get_pledge(pledge_id)
        assert pledge is not None
        assert len(_normalize_refunds(pledge)) == 2
        assert refunded_amount_from_pledge(pledge) == pytest.approx(5.0)

    asyncio.run(run())


def test_refund_above_remaining_raises_without_paypal(monkeypatch):
    async def run():
        client = CountingPayPal()
        pledge_id = await _captured(client, monkeypatch)
        await refund_pledge(pledge_id, client, amount_eur="4.00")
        assert client.refund_n == 1
        with pytest.raises(ValueError, match="remaining refundable"):
            await refund_pledge(pledge_id, client, amount_eur="7.00")
        assert client.refund_n == 1

    asyncio.run(run())
