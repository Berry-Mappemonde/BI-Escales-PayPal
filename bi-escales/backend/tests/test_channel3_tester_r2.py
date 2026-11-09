"""Tester r2 fixes: JPY minor units, ledger totals_by_currency, refunds, wishlist qty."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.channel3_funding import enrich_item_funding, fund_snapshot_for_project
from app.escales.ledger import fund_for_milestone, record_finance, reset_ledger, to_public_fund
from app.channel3_catalog import project_id_for_product
from app.escales.ledger import reset_ledger
from app.escales.pledges import authorize_pledge, create_pledge, refund_pledge
from app.routers.escales import router, set_paypal_client_factory
from tests.test_escales_pledges import Spy


class RefundTrackingSpy(Spy):
    def __init__(self):
        super().__init__()
        self.refund_calls: list[dict] = []

    def refund_capture(self, capture_id, **kwargs):
        self.refund_calls.append(dict(kwargs))
        return super().refund_capture(capture_id, **kwargs)


ADMIN = "treasurer-key"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", ADMIN)
    monkeypatch.setenv("ESCALES_CHANNEL3_ENABLED", "1")
    monkeypatch.setenv("ESCALES_WISHLISTS_ENABLED", "1")
    reset_ledger()
    set_paypal_client_factory(lambda: Spy())
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client
    set_paypal_client_factory(None)


def test_jpy_funded_pct_uses_whole_minor_units():
    item = {
        "price_currency": "JPY",
        "catalog_default_target_amount_minor": 1200,
        "catalog_default_target_currency": "JPY",
        "price_amount_minor": 1200,
    }
    fund = {"currency": "JPY", "captured_eur": "600", "amount_eur": "600"}
    enriched = enrich_item_funding(item, fund)
    assert enriched["funded_amount_minor"] == 600
    assert enriched["funded_pct"] == 50
    assert enriched["fully_funded"] is False
    assert enriched.get("buy_link") in (None, "")


def test_projet_fund_splits_eur_and_usd(api):
    async def _seed():
        await record_finance(
            "pledge_captured",
            amount_eur="10.00",
            currency="EUR",
            milestone_id="",
            target_id="projet",
            pledge_kind="project_pledge",
        )
        await record_finance(
            "pledge_captured",
            amount_eur="9.99",
            currency="USD",
            milestone_id="projet",
            target_id="gear-c3-hwd0sf9",
            pledge_kind="project_pledge",
        )

    asyncio.run(_seed())
    fund = asyncio.run(fund_for_milestone("projet"))
    public = to_public_fund(fund)
    assert public["income_eur"] == "10.00"
    assert public["totals_by_currency"]["USD"]["captured"] == "9.99"
    assert public["totals_by_currency"]["EUR"]["captured"] == "10.00"


def test_wishlist_quantity_zero_returns_400(api):
    create = api.post(
        "/api/escales/treasurer/wishlists",
        headers={"x-admin-key": ADMIN},
        json={"title": "q0", "slug": "q0", "items": []},
    )
    wid = create.json()["_id"]
    res = api.post(
        f"/api/escales/treasurer/wishlists/{wid}/items",
        headers={"x-admin-key": ADMIN},
        json={"channel3_product_id": "QE0Vp6a", "quantity": 0},
    )
    assert res.status_code == 400
    negative = api.post(
        f"/api/escales/treasurer/wishlists/{wid}/items",
        headers={"x-admin-key": ADMIN},
        json={"channel3_product_id": "hwD0sF9", "quantity": -1},
    )
    assert negative.status_code == 400


def test_usd_refund_uses_pledge_currency(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    reset_ledger()
    spy = RefundTrackingSpy()
    pid = project_id_for_product("QE0Vp6a")

    async def _run():
        doc = await create_pledge(
            amount_eur="39.99",
            description="USD gear",
            milestone_id="",
            kind="project_pledge",
            target_id=pid,
            client=spy,
        )
        assert doc["currency"] == "USD"
        captured = await authorize_pledge(doc["_id"], spy)
        assert captured["status"] == "captured"
        refunded = await refund_pledge(captured["_id"], spy, amount_eur="4.00")
        assert refunded.get("status") in {"partially_refunded", "refunded"}
        assert spy.refund_calls[-1]["currency_code"] == "USD"
        assert spy.refund_calls[-1]["amount_eur"] == "4.00"
        snap = await fund_snapshot_for_project(pid)
        assert snap["currency"] == "USD"
        assert snap["captured_eur"] == "35.99"

    asyncio.run(_run())


def test_jpy_refund_whole_units(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    reset_ledger()
    spy = RefundTrackingSpy()

    def _fake_lookup(project_id: str, **kwargs):
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
    monkeypatch.setattr("app.channel3_funding.lookup_catalog_by_project_id", _fake_lookup)

    async def _run():
        doc = await create_pledge(
            amount_eur="1200",
            description="JPY gear",
            milestone_id="",
            kind="project_pledge",
            target_id="gear-c3-jpy1",
            client=spy,
        )
        assert doc["currency"] == "JPY"
        capture_orders = [c for c in spy.calls if c[0] == "create_capture"]
        assert capture_orders[-1][1] == "1200"
        captured = await authorize_pledge(doc["_id"], spy)
        await refund_pledge(captured["_id"], spy, amount_eur="300")
        assert spy.refund_calls[-1]["currency_code"] == "JPY"
        assert spy.refund_calls[-1]["amount_eur"] == "300"
        snap = await fund_snapshot_for_project("gear-c3-jpy1")
        assert snap["captured_eur"] == "900"

    asyncio.run(_run())
