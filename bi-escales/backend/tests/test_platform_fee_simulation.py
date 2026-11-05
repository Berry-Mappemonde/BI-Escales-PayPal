"""In-app marina platform fee when PayPal partner merchant IDs are missing."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.ledger import list_finance_entries
from app.escales.pledges import authorize_pledge, capture_pledge, create_pledge, reset_ledger
from app.routers.escales import set_paypal_client_factory
from tests.test_paypal_b9_b12 import CaptureSpy


@pytest.fixture(autouse=True)
def memory_store(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_MARINA_PAYOUT_EMAIL", "marina-sandbox@example.com")
    reset_ledger()
    yield
    reset_ledger()
    set_paypal_client_factory(None)


@pytest.fixture
def allow_capture(monkeypatch):
    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.escales.departure_clock.refuse_early_capture", noop)
    monkeypatch.setattr("app.escales.departure_clock.refuse_early_authorization", noop)


class PayoutSpy(CaptureSpy):
    def __init__(self):
        super().__init__()
        self.payout_calls: list[dict] = []

    def create_payout(self, **kwargs):
        self.payout_calls.append(kwargs)
        return {"batch_header": {"payout_batch_id": "BATCH-MARINA-1", "batch_status": "PENDING"}}


def test_berth_capture_sends_marina_payout_and_records_fee(monkeypatch, allow_capture):
    monkeypatch.setenv("ESCALES_PLATFORM_FEE_EUR", "3.00")
    monkeypatch.delenv("ESCALES_PLATFORM_FEES_ENABLED", raising=False)
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-12T08:00:00Z")
    spy = PayoutSpy()
    set_paypal_client_factory(lambda: spy)

    async def body():
        created = await create_pledge(
            amount_eur="30.00",
            description="Place de port",
            milestone_id="dep-mayotte",
            client=spy,
            kind="berth",
            target_id="dzaoudzi-mayotte",
        )
        await authorize_pledge(created["_id"], spy)
        captured = await capture_pledge(created["_id"], spy)
        assert captured["platform_fee_eur"] == "3.00"
        assert captured["marina_net_eur"] == "27.00"
        assert captured.get("marina_payout_batch_id") == "BATCH-MARINA-1"
        assert captured.get("marina_payout_status") == "pending"
        assert len(spy.payout_calls) == 1
        assert spy.payout_calls[0]["receiver_email"] == "marina-sandbox@example.com"
        assert spy.payout_calls[0]["amount_eur"] == "27.00"
        kinds = [row["kind"] for row in await list_finance_entries()]
        assert kinds.count("marina_platform_fee") == 1
        assert kinds.count("marina_payout_sent") == 1

    asyncio.run(body())


def test_mile_capture_skips_marina_settlement(monkeypatch, allow_capture):
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-12T08:00:00Z")
    spy = PayoutSpy()
    set_paypal_client_factory(lambda: spy)

    async def body():
        created = await create_pledge(
            amount_eur="20.00",
            description="Milles",
            milestone_id="dep-mayotte",
            client=spy,
            kind="mile",
        )
        await authorize_pledge(created["_id"], spy)
        captured = await capture_pledge(created["_id"], spy)
        assert not captured.get("marina_payout_batch_id")
        assert spy.payout_calls == []

    asyncio.run(body())


def test_paypal_multiparty_skips_marina_payout(monkeypatch, allow_capture):
    monkeypatch.setenv("ESCALES_PLATFORM_FEES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_PLATFORM_PAYEE_MERCHANT_ID", "PLATFORM1")
    monkeypatch.setenv("ESCALES_MARINA_SELLER_MERCHANT_ID", "SELLER1")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-12T08:00:00Z")
    spy = PayoutSpy()
    set_paypal_client_factory(lambda: spy)

    async def body():
        created = await create_pledge(
            amount_eur="30.00",
            description="Place de port",
            milestone_id="dep-mayotte",
            client=spy,
            kind="berth",
            target_id="dzaoudzi-mayotte",
        )
        await authorize_pledge(created["_id"], spy)
        captured = await capture_pledge(created["_id"], spy)
        assert not captured.get("marina_payout_batch_id")
        assert spy.payout_calls == []

    asyncio.run(body())
