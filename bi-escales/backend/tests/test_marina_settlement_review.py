"""Hamid review: marina payout receiver, retry-safe fee, card/vault fallback, fund payouts."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.ledger import fund_for_milestone, list_finance_entries
from app.escales.marina_berth_settlement import should_settle_marina_berth_capture
from app.escales.marina_payout_email import resolve_marina_payout_email_sync
from app.escales.paypal_client import PayPalError
from app.escales.pledges import (
    authorize_pledge,
    capture_pledge,
    create_pledge,
    get_ledger,
    record_pledge_captured_once,
    reset_ledger,
)
from app.routers.escales import set_paypal_client_factory
from tests.test_paypal_b9_b12 import CaptureSpy

SNAPSHOT = {
    "escales": {
        "Ajaccio (Corse)": {
            "sections": {"mooring": {"marinas": [{"name": "Aspretto", "email": "first-catalog@example.com"}]}}
        },
        "La Rochelle": {
            "sections": {
                "mooring": {
                    "marinas": [
                        {"name": "Bassin des Tamaris", "osm_id": "w1", "email": "tamaris@example.com"},
                        {"name": "Port des Minimes", "osm_id": "w2", "payout_email": "minimes@example.com"},
                        {"name": "Bassin Lazaret", "osm_id": "w3"},
                    ]
                }
            }
        },
    }
}


@pytest.fixture
def catalog(monkeypatch):
    monkeypatch.setattr("app.bi_marinas_catalog.load_bundled_escale_snapshot", lambda: SNAPSHOT)
    monkeypatch.setenv("ESCALES_MARINA_PAYOUT_EMAIL", "fallback@example.com")


def test_payout_email_comes_from_the_pledge_marina(catalog):
    pledge = {"kind": "berth", "target_id": "la-rochelle", "description": "Place de port — Port des Minimes"}
    assert resolve_marina_payout_email_sync(pledge) == "minimes@example.com"
    pledge = {"kind": "berth", "target_id": "dep-la-rochelle", "marina_osm_id": "w1"}
    assert resolve_marina_payout_email_sync(pledge) == "tamaris@example.com"


def test_payout_email_never_borrows_another_marina(catalog):
    # Marina without an email, and an unknown marina: never the first catalog row.
    no_email = {"kind": "berth", "target_id": "la-rochelle", "description": "Place — Bassin Lazaret"}
    unknown = {"kind": "berth", "target_id": "la-rochelle", "description": "Place de port"}
    other_stop = {"kind": "berth", "target_id": "dzaoudzi-mayotte", "description": "Aspretto"}
    for pledge in (no_email, unknown, other_stop):
        assert resolve_marina_payout_email_sync(pledge) == "fallback@example.com"


def test_payout_email_empty_without_fallback(catalog, monkeypatch):
    monkeypatch.delenv("ESCALES_MARINA_PAYOUT_EMAIL", raising=False)
    assert resolve_marina_payout_email_sync({"target_id": "la-rochelle", "description": "x"}) == ""


@pytest.fixture
def memory(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_MARINA_PAYOUT_EMAIL", "marina-sandbox@example.com")
    monkeypatch.setenv("ESCALES_PLATFORM_FEE_EUR", "3.00")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-12T08:00:00Z")
    monkeypatch.delenv("ESCALES_PLATFORM_FEES_ENABLED", raising=False)

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.escales.departure_clock.refuse_early_capture", noop)
    monkeypatch.setattr("app.escales.departure_clock.refuse_early_authorization", noop)
    reset_ledger()
    yield
    reset_ledger()
    set_paypal_client_factory(None)


class FlakyPayout(CaptureSpy):
    def __init__(self, failures: int = 1):
        super().__init__()
        self.failures = failures
        self.payout_calls: list[dict] = []

    def create_payout(self, **kwargs):
        self.payout_calls.append(kwargs)
        if self.failures > 0:
            self.failures -= 1
            raise PayPalError(503, {"name": "SERVICE_UNAVAILABLE"})
        return {"batch_header": {"payout_batch_id": "BATCH-OK", "batch_status": "PENDING"}}


async def _captured_berth(spy, **extra) -> dict:
    created = await create_pledge(
        amount_eur="30.00",
        description="Place de port",
        milestone_id="dep-mayotte",
        client=spy,
        kind="berth",
        target_id="dzaoudzi-mayotte",
        **extra,
    )
    await authorize_pledge(created["_id"], spy)
    return await capture_pledge(created["_id"], spy)


def _kinds(rows):
    return [row["kind"] for row in rows]


def test_fee_recorded_only_after_successful_payout_and_retry_works(memory, monkeypatch):
    monkeypatch.setenv("ESCALES_MARINA_PAYOUTS_ENABLED", "1")
    spy = FlakyPayout(failures=1)
    set_paypal_client_factory(lambda: spy)

    async def body():
        captured = await _captured_berth(spy)
        assert captured["marina_payout_status"] == "failed"
        kinds = _kinds(await list_finance_entries())
        assert "marina_platform_fee" not in kinds
        assert "marina_payout_sent" not in kinds

        retried = await record_pledge_captured_once(captured, actor="retry", client=spy)
        assert retried["marina_payout_status"] == "pending"
        assert retried["marina_payout_batch_id"] == "BATCH-OK"
        assert len(spy.payout_calls) == 2
        # Same deterministic sender_batch_id on the retry: PayPal dedupes a resend.
        assert spy.payout_calls[0]["batch_id"] == spy.payout_calls[1]["batch_id"]

        again = await record_pledge_captured_once(retried, actor="retry", client=spy)
        assert len(spy.payout_calls) == 2
        kinds = _kinds(await list_finance_entries())
        assert kinds.count("marina_platform_fee") == 1
        assert kinds.count("marina_payout_sent") == 1
        assert kinds.count("pledge_captured") == 1
        saved = await get_ledger().get_pledge(again["_id"])
        assert saved["marina_payout_status"] == "pending"

    asyncio.run(body())


def test_card_order_falls_back_to_payout_when_multiparty_is_configured(memory, monkeypatch):
    monkeypatch.delenv("ESCALES_MARINA_PAYOUTS_ENABLED", raising=False)
    monkeypatch.setenv("ESCALES_PLATFORM_FEES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_PLATFORM_PAYEE_MERCHANT_ID", "PLATFORM1")
    monkeypatch.setenv("ESCALES_MARINA_SELLER_MERCHANT_ID", "SELLER1")
    card = {"kind": "berth", "target_id": "dzaoudzi-mayotte", "platform_fees_on_order": False}
    multiparty = {"kind": "berth", "target_id": "dzaoudzi-mayotte", "platform_fees_on_order": True}
    legacy_vault = {"kind": "berth", "target_id": "dzaoudzi-mayotte", "vault_on_purchase": True}
    legacy_card = {"kind": "berth", "target_id": "dzaoudzi-mayotte", "checkout_method": "card"}
    legacy_wallet = {"kind": "berth", "target_id": "dzaoudzi-mayotte", "checkout_method": "paypal"}
    assert should_settle_marina_berth_capture(card) is True
    assert should_settle_marina_berth_capture(legacy_vault) is True
    assert should_settle_marina_berth_capture(legacy_card) is True
    assert should_settle_marina_berth_capture(multiparty) is False
    assert should_settle_marina_berth_capture(legacy_wallet) is False


def test_vault_order_pays_marina_when_multiparty_cannot_ride_the_order(memory, monkeypatch):
    monkeypatch.delenv("ESCALES_MARINA_PAYOUTS_ENABLED", raising=False)
    monkeypatch.setenv("ESCALES_PLATFORM_FEES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_PLATFORM_PAYEE_MERCHANT_ID", "PLATFORM1")
    monkeypatch.setenv("ESCALES_MARINA_SELLER_MERCHANT_ID", "SELLER1")
    spy = FlakyPayout(failures=0)

    async def body():
        pledge = await get_ledger().insert_pledge_once(
            {
                "_id": "vault-berth-1",
                "status": "captured",
                "kind": "berth",
                "amount_eur": "30.00",
                "currency": "EUR",
                "milestone_id": "dep-mayotte",
                "target_id": "dzaoudzi-mayotte",
                "checkout_method": "paypal",
                "vault_on_purchase": True,
                "platform_fees_on_order": False,
                "capture_id": "CAP-V1",
                "history": ["captured"],
            }
        )
        settled = await record_pledge_captured_once(pledge, actor="test", client=spy)
        assert settled["marina_payout_batch_id"] == "BATCH-OK"
        assert spy.payout_calls[0]["amount_eur"] == "27.00"
        kinds = _kinds(await list_finance_entries())
        assert kinds.count("marina_platform_fee") == 1

    asyncio.run(body())


def test_fund_balance_subtracts_marina_payouts(memory, monkeypatch):
    monkeypatch.setenv("ESCALES_MARINA_PAYOUTS_ENABLED", "1")
    spy = FlakyPayout(failures=0)
    set_paypal_client_factory(lambda: spy)

    async def body():
        await _captured_berth(spy)
        fund = await fund_for_milestone("dep-mayotte")
        assert fund["income_eur"] == "30.00"
        assert fund["payouts_eur"] == "27.00"
        assert fund["balance_eur"] == "3.00"
        assert [row["kind"] for row in fund["payouts"]] == ["marina_payout_sent"]
        assert "receiver_email" not in fund["payouts"][0]

    asyncio.run(body())


def test_denied_payout_does_not_reduce_the_fund(memory, monkeypatch):
    from app.escales.marina_berth_settlement import apply_payout_batch_webhook

    monkeypatch.setenv("ESCALES_MARINA_PAYOUTS_ENABLED", "1")
    spy = FlakyPayout(failures=0)
    set_paypal_client_factory(lambda: spy)

    async def body():
        await _captured_berth(spy)
        await apply_payout_batch_webhook(
            batch_id="BATCH-OK", event_type="PAYMENT.PAYOUTSBATCH.DENIED", batch_status="DENIED"
        )
        fund = await fund_for_milestone("dep-mayotte")
        assert fund["payouts_eur"] == "0.00"
        assert fund["balance_eur"] == "30.00"

    asyncio.run(body())
