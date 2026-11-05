"""In-app marina platform fee when PayPal partner merchant IDs are missing."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.ledger import list_finance_entries
from app.escales.pledges import authorize_pledge, capture_pledge, create_pledge, reset_ledger
from tests.test_paypal_b9_b12 import CaptureSpy


@pytest.fixture(autouse=True)
def memory_store(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    reset_ledger()
    yield
    reset_ledger()


@pytest.fixture
def allow_capture(monkeypatch):
    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.escales.departure_clock.refuse_early_capture", noop)
    monkeypatch.setattr("app.escales.departure_clock.refuse_early_authorization", noop)


def test_berth_capture_simulates_platform_fee_in_ledger(monkeypatch, allow_capture):
    monkeypatch.setenv("ESCALES_PLATFORM_FEE_EUR", "3.00")
    monkeypatch.delenv("ESCALES_PLATFORM_FEES_ENABLED", raising=False)
    monkeypatch.delenv("ESCALES_PLATFORM_PAYEE_MERCHANT_ID", raising=False)
    monkeypatch.delenv("ESCALES_MARINA_SELLER_MERCHANT_ID", raising=False)
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-12T08:00:00Z")

    async def body():
        spy = CaptureSpy()
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
        assert captured["platform_fee_simulated"] is True
        assert captured["platform_fee_eur"] == "3.00"
        assert captured["marina_net_eur"] == "27.00"
        kinds = [row["kind"] for row in await list_finance_entries()]
        assert kinds.count("platform_fee_simulated") == 1
        assert kinds.count("marina_net_simulated") == 1

    asyncio.run(body())


def test_mile_capture_skips_platform_fee_simulation(monkeypatch, allow_capture):
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-12T08:00:00Z")

    async def body():
        spy = CaptureSpy()
        created = await create_pledge(
            amount_eur="20.00",
            description="Milles",
            milestone_id="dep-mayotte",
            client=spy,
            kind="mile",
        )
        await authorize_pledge(created["_id"], spy)
        captured = await capture_pledge(created["_id"], spy)
        assert not captured.get("platform_fee_simulated")
        kinds = [row["kind"] for row in await list_finance_entries()]
        assert "platform_fee_simulated" not in kinds

    asyncio.run(body())


def test_paypal_multiparty_skips_in_app_simulation(monkeypatch, allow_capture):
    monkeypatch.setenv("ESCALES_PLATFORM_FEES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_PLATFORM_PAYEE_MERCHANT_ID", "PLATFORM1")
    monkeypatch.setenv("ESCALES_MARINA_SELLER_MERCHANT_ID", "SELLER1")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-12T08:00:00Z")

    async def body():
        spy = CaptureSpy()
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
        assert not captured.get("platform_fee_simulated")
        kinds = [row["kind"] for row in await list_finance_entries()]
        assert "platform_fee_simulated" not in kinds

    asyncio.run(body())
