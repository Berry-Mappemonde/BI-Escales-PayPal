"""C3-APP-SETTLE: PayPal seller receivable/payable breakdown and received_net_eur."""
from __future__ import annotations

import asyncio
import logging
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.channel3_catalog import project_id_for_product
from app.channel3_funding import fund_snapshot_for_project
from app.escales.ledger import fund_for_milestone, reset_ledger, to_public_fund
from app.escales.ledger import get_ledger
from app.escales.paypal_settlement import (
    apply_capture_settlement,
    apply_refund_settlement,
    enrich_refund_row_settlement,
    parse_seller_receivable_breakdown,
    pledge_spendable_net_eur,
    recompute_received_net_eur,
)
from app.escales.pledges import (
    authorize_pledge,
    create_pledge,
    reconcile_refund_on_pledge,
    refund_pledge,
    _normalize_refunds,
)
from app.escales.project_payouts import (
    project_captured_eur,
    project_payout_available_eur,
    propose_project_payout,
)
from tests.test_escales_pledges import Spy


def _breakdown(ccy: str, gross: str, fee: str, net_eur: str, rate: str) -> dict:
    return {
        "gross_amount": {"currency_code": ccy, "value": gross},
        "paypal_fee": {"currency_code": ccy, "value": fee},
        "net_amount": {"currency_code": "EUR", "value": net_eur},
        "receivable_amount": {"currency_code": "EUR", "value": net_eur},
        "exchange_rate": {
            "source_currency": ccy,
            "target_currency": "EUR",
            "value": rate,
        },
    }


class SettlementSpy(Spy):
    def __init__(self, capture_body: dict | None = None, refund_body: dict | None = None):
        super().__init__()
        self._capture_body = capture_body
        self._refund_body = refund_body

    def capture_order(self, order_id, **kwargs):
        self.calls.append(("orders.capture", order_id))
        cap = {"id": f"CAP-{order_id}", "status": "COMPLETED"}
        if self._capture_body:
            cap.update(self._capture_body)
        return {
            "id": order_id,
            "status": "COMPLETED",
            "purchase_units": [{"payments": {"captures": [cap]}}],
        }

    def capture_authorization(self, authorization_id, final=True, **kwargs):
        self.calls.append(("capture", authorization_id))
        cap = {"id": "CAP-EUR", "status": "COMPLETED"}
        if self._capture_body:
            cap.update(self._capture_body)
        return cap

    def refund_capture(self, capture_id, **kwargs):
        self.calls.append(("refund", capture_id, kwargs.get("amount_eur")))
        body = {"id": "REF-SETTLE", "status": "COMPLETED"}
        if self._refund_body:
            body.update(self._refund_body)
        return body


@pytest.mark.parametrize(
    "currency,gross,fee,net,rate",
    [
        ("USD", "1.00", "0.14", "0.86", "0.8600"),
        ("GBP", "2.50", "0.20", "2.70", "1.1200"),
    ],
)
def test_capture_stores_receivable_breakdown(currency, gross, fee, net, rate):
    capture = {
        "id": "CAP-X",
        "status": "COMPLETED",
        "seller_receivable_breakdown": _breakdown(currency, gross, fee, net, rate),
    }
    parsed = parse_seller_receivable_breakdown(capture)
    assert parsed["gross_amount"]["value"] == gross
    assert parsed["net_amount"]["value"] == net
    pledge = {"_id": "p1", "currency": currency, "amount_eur": gross}
    pledge = apply_capture_settlement(pledge, capture)
    assert pledge["received_net_eur"] == net
    assert pledge["capture_settlement"]["exchange_rate"]["value"] == rate


def test_jpy_capture_net_eur(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    reset_ledger()

    def _fake_lookup(project_id: str):
        return {
            "channel3_product_id": "jpy1",
            "project_id": project_id,
            "price_currency": "JPY",
            "price_amount_minor": 1200,
            "unit_price_amount_minor": 1200,
            "catalog_default_target_amount_minor": 1200,
            "catalog_default_target_currency": "JPY",
        }

    monkeypatch.setattr("app.channel3_catalog.lookup_catalog_by_project_id", _fake_lookup)
    spy = SettlementSpy(
        capture_body={
            "seller_receivable_breakdown": _breakdown("JPY", "1200", "70", "7.20", "0.0060"),
        },
    )

    async def _run():
        doc = await create_pledge(
            amount_eur="1200",
            description="JPY item",
            milestone_id="",
            kind="project_pledge",
            target_id="gear-c3-jpy1",
            client=spy,
        )
        captured = await authorize_pledge(doc["_id"], spy)
        assert captured["received_net_eur"] == "7.20"
        snap = await fund_snapshot_for_project("gear-c3-jpy1")
        assert snap["received_net_eur"] == "7.20"
        assert snap["totals_by_currency"]["JPY"]["captured"] == "1200"

    asyncio.run(_run())


def test_eur_capture_unchanged_without_full_breakdown():
    pledge = {"_id": "eur1", "currency": "EUR", "amount_eur": "20.00"}
    pledge = apply_capture_settlement(pledge, {"id": "CAP", "status": "COMPLETED"})
    assert pledge["received_net_eur"] == "20.00"
    assert pledge.get("capture_settlement") is None


def test_missing_breakdown_logs_warning(caplog, monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    reset_ledger()
    spy = SettlementSpy(capture_body={})
    pid = project_id_for_product("hwD0sF9")

    async def _run():
        doc = await create_pledge(
            amount_eur="9.99",
            description="USD no breakdown",
            milestone_id="",
            kind="project_pledge",
            target_id=pid,
            client=spy,
        )
        captured = await authorize_pledge(doc["_id"], spy)
        assert captured.get("received_net_eur") is None
        assert captured.get("capture_settlement") is None
        assert await project_captured_eur(pid) == Decimal("0.00")

    with caplog.at_level(logging.WARNING):
        asyncio.run(_run())
    assert any("seller_receivable_breakdown" in r.message for r in caplog.records)


def test_usd_refund_reversal_reduces_received_net_eur(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    reset_ledger()
    pid = project_id_for_product("hwD0sF9")
    spy = SettlementSpy(
        capture_body={
            "seller_receivable_breakdown": _breakdown("USD", "9.99", "0.50", "8.00", "0.86"),
        },
        refund_body={
            "seller_payable_breakdown": {
                "net_amount": {"currency_code": "EUR", "value": "3.50"},
            },
        },
    )

    async def _run():
        doc = await create_pledge(
            amount_eur="9.99",
            description="USD refund",
            milestone_id="",
            kind="project_pledge",
            target_id=pid,
            client=spy,
        )
        captured = await authorize_pledge(doc["_id"], spy)
        assert captured["received_net_eur"] == "8.00"
        refunded = await refund_pledge(captured["_id"], spy, amount_eur="4.00")
        assert refunded["received_net_eur"] == "4.50"
        snap = await fund_snapshot_for_project(pid)
        assert snap["received_net_eur"] == "4.50"

    asyncio.run(_run())


def test_payout_bounded_by_received_net_eur(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    reset_ledger()
    pid = project_id_for_product("hwD0sF9")
    spy = SettlementSpy(
        capture_body={
            "seller_receivable_breakdown": _breakdown("USD", "9.99", "0.50", "8.00", "0.86"),
        },
    )

    async def _run():
        doc = await create_pledge(
            amount_eur="9.99",
            description="USD payout cap",
            milestone_id="",
            kind="project_pledge",
            target_id=pid,
            client=spy,
        )
        await authorize_pledge(doc["_id"], spy)
        assert await project_captured_eur(pid) == Decimal("8.00")
        assert await project_payout_available_eur(pid) == Decimal("8.00")
        with pytest.raises(ValueError, match="exceeds captured"):
            await propose_project_payout(pid, amount_eur="9.99", receiver_email="payee@example.com")
        ok = await propose_project_payout(pid, amount_eur="8.00", receiver_email="payee@example.com")
        assert ok["amount_eur"] == "8.00"

    asyncio.run(_run())


def test_projet_fund_includes_received_net_eur(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    reset_ledger()
    pid = project_id_for_product("hwD0sF9")
    spy = SettlementSpy(
        capture_body={
            "seller_receivable_breakdown": _breakdown("USD", "1.00", "0.14", "0.86", "0.8600"),
        },
    )

    async def _run():
        doc = await create_pledge(
            amount_eur="1.00",
            description="USD fund",
            milestone_id="",
            kind="project_pledge",
            target_id=pid,
            client=spy,
        )
        await authorize_pledge(doc["_id"], spy)
        fund = await fund_for_milestone(pid)
        public = to_public_fund(fund)
        assert public["received_net_eur"] == "0.86"
        assert public["totals_by_currency"]["USD"]["captured"] == "1.00"

    asyncio.run(_run())


def test_refund_settlement_unit():
    pledge = {
        "_id": "p",
        "currency": "USD",
        "capture_received_net_eur": "8.00",
        "received_net_eur": "8.00",
        "refunds": [],
    }
    row = {"id": "R1", "amount": "4.00", "status": "COMPLETED", "at": "2026-11-12T00:00:00+00:00"}
    payload = {
        "seller_payable_breakdown": {
            "net_amount": {"currency_code": "EUR", "value": "3.50"},
        },
    }
    pledge, row = apply_refund_settlement(pledge, payload, row)
    assert row["refund_net_eur"] == "3.50"
    assert pledge["received_net_eur"] == "4.50"


def test_refund_reconcile_idempotent_usd_webhook_replay(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    reset_ledger()
    project_id = "gear-c3-idem-usd"
    payload = {
        "seller_payable_breakdown": {
            "net_amount": {"currency_code": "EUR", "value": "3.50"},
        },
    }

    async def _run():
        pledge = {
            "_id": "pledge-idem-usd",
            "kind": "project_pledge",
            "target_id": project_id,
            "currency": "USD",
            "amount_eur": "9.99",
            "status": "captured",
            "capture_received_net_eur": "8.00",
            "received_net_eur": "8.00",
            "capture_settlement": {
                "net_amount": {"currency": "EUR", "value": "8.00"},
                "exchange_rate": {
                    "source_currency": "USD",
                    "target_currency": "EUR",
                    "value": "0.8600",
                },
            },
            "refunds": [],
        }
        await get_ledger().save_pledge(pledge)
        for _ in range(3):
            current = await get_ledger().get_pledge("pledge-idem-usd")
            assert current is not None
            await reconcile_refund_on_pledge(
                current,
                refund_id="REF-SAME",
                amount_eur="4.00",
                refund_payload=payload,
            )
        final = await get_ledger().get_pledge("pledge-idem-usd")
        assert final["received_net_eur"] == "4.50"
        assert len(_normalize_refunds(final)) == 1
        assert await project_captured_eur(project_id) == Decimal("4.50")
        assert await project_payout_available_eur(project_id) == Decimal("4.50")

    asyncio.run(_run())


def test_refund_reconcile_idempotent_eur_webhook_replay(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    reset_ledger()
    project_id = "projet-idem-eur"

    async def _run():
        pledge = {
            "_id": "pledge-idem-eur",
            "kind": "project_pledge",
            "target_id": project_id,
            "currency": "EUR",
            "amount_eur": "20.00",
            "status": "captured",
            "capture_received_net_eur": "20.00",
            "received_net_eur": "20.00",
            "refunds": [],
        }
        await get_ledger().save_pledge(pledge)
        for _ in range(3):
            current = await get_ledger().get_pledge("pledge-idem-eur")
            assert current is not None
            await reconcile_refund_on_pledge(
                current,
                refund_id="REF-EUR-SAME",
                amount_eur="3.50",
                status="COMPLETED",
            )
        final = await get_ledger().get_pledge("pledge-idem-eur")
        assert final["received_net_eur"] == "16.50"
        assert len(_normalize_refunds(final)) == 1
        assert await project_captured_eur(project_id) == Decimal("16.50")

    asyncio.run(_run())


def test_capture_usd_net_amount_leaves_received_net_eur_unset():
    payload = {
        "id": "CAP-USD-NET",
        "status": "COMPLETED",
        "seller_receivable_breakdown": {
            "gross_amount": {"currency_code": "USD", "value": "10.00"},
            "paypal_fee": {"currency_code": "USD", "value": "0.64"},
            "net_amount": {"currency_code": "USD", "value": "9.36"},
        },
    }
    pledge = {
        "_id": "pledge-usd-net",
        "kind": "project_pledge",
        "target_id": "gear-c3-usd-net",
        "currency": "USD",
        "amount_eur": "10.00",
        "status": "captured",
    }
    pledge = apply_capture_settlement(pledge, payload)
    assert isinstance(pledge.get("capture_settlement"), dict)
    assert pledge.get("received_net_eur") is None
    assert pledge.get("capture_received_net_eur") is None
    assert pledge_spendable_net_eur(pledge) == Decimal("0.00")


def test_refund_after_usd_net_capture_does_not_raise_received_net(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    reset_ledger()
    project_id = "gear-c3-usd-net"

    async def _run():
        pledge = {
            "_id": "pledge-usd-net-ref",
            "kind": "project_pledge",
            "target_id": project_id,
            "currency": "USD",
            "amount_eur": "10.00",
            "status": "captured",
            "capture_settlement": {
                "net_amount": {"currency": "USD", "value": "9.36"},
            },
            "refunds": [],
        }
        await get_ledger().save_pledge(pledge)
        current = await get_ledger().get_pledge("pledge-usd-net-ref")
        await reconcile_refund_on_pledge(
            current,
            refund_id="REF-USD-NET",
            amount_eur="5.00",
            refund_payload={
                "seller_payable_breakdown": {
                    "net_amount": {"currency_code": "EUR", "value": "4.00"},
                },
            },
        )
        final = await get_ledger().get_pledge("pledge-usd-net-ref")
        assert final.get("received_net_eur") is None
        assert await project_captured_eur(project_id) == Decimal("0.00")

    asyncio.run(_run())


def test_refund_without_payable_uses_capture_rate_conservative():
    pledge = {
        "_id": "p2",
        "currency": "USD",
        "capture_received_net_eur": "8.00",
        "capture_settlement": {
            "exchange_rate": {
                "source_currency": "USD",
                "target_currency": "EUR",
                "value": "0.8600",
            },
        },
    }
    row = {"id": "R2", "amount": "4.00", "status": "COMPLETED"}
    enriched = enrich_refund_row_settlement(pledge, {}, row)
    assert enriched["refund_net_eur"] == "3.44"
    pledge["refunds"] = [enriched]
    recompute_received_net_eur(pledge, pledge["refunds"])
    assert pledge["received_net_eur"] == "4.56"
