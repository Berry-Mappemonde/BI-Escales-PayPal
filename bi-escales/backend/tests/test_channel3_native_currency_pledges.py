"""Native-currency Channel3 catalogue pledges (PayPal mocked)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.channel3_catalog import project_id_for_product
from app.channel3_paypal import (
    PAYPAL_CURRENCY_CODES_URL,
    PAYPAL_SUPPORTED_CURRENCY_CODES,
    format_paypal_amount_value,
)
from app.escales.ledger import record_finance, reset_ledger
from app.escales.pledges import create_pledge
from app.routers.escales import router, set_paypal_client_factory


class CaptureOrderSpy:
    def __init__(self):
        self.orders: list[dict] = []

    def create_capture_order(
        self,
        amount_eur,
        description,
        reference_id,
        idempotency_key=None,
        **kwargs,
    ):
        payload = {
            "amount_eur": amount_eur,
            "currency_code": kwargs.get("currency_code"),
            "reference_id": reference_id,
        }
        self.orders.append(payload)
        order_id = f"ORD-{len(self.orders)}"
        return {
            "id": order_id,
            "status": "CREATED",
            "links": [{"rel": "approve", "href": f"https://sandbox.paypal.com/checkout?token={order_id}"}],
        }

    def get_order(self, order_id):
        return {"id": order_id, "status": "APPROVED"}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_CHANNEL3_ENABLED", "1")
    monkeypatch.setenv("ESCALES_WISHLISTS_ENABLED", "1")
    reset_ledger()
    spy = CaptureOrderSpy()
    set_paypal_client_factory(lambda: spy)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client, spy
    set_paypal_client_factory(None)


def test_paypal_allow_list_matches_documented_set():
    expected = {
        "AUD", "BRL", "CAD", "CNY", "CZK", "DKK", "EUR", "HKD", "HUF", "ILS", "JPY", "MYR", "MXN",
        "TWD", "NZD", "NOK", "PHP", "PLN", "GBP", "SGD", "SEK", "CHF", "THB", "USD",
    }
    assert PAYPAL_SUPPORTED_CURRENCY_CODES == expected
    assert "developer.paypal.com/reference/currency-codes" in PAYPAL_CURRENCY_CODES_URL


def test_jpy_paypal_value_has_no_decimals():
    assert format_paypal_amount_value("1200", "JPY") == "1200"
    assert format_paypal_amount_value("10.00", "EUR") == "10.00"


def test_usd_catalog_pledge_creates_usd_order(api):
    client, spy = api
    pid = project_id_for_product("QE0Vp6a")
    res = client.post(
        "/api/escales/pledges",
        json={
            "amount_eur": "39.99",
            "currency": "EUR",
            "description": "Bilge pump",
            "milestone_id": "",
            "kind": "project_pledge",
            "target_id": pid,
        },
    )
    assert res.status_code == 200
    order = spy.orders[-1]
    assert order["currency_code"] == "USD"
    assert order["amount_eur"] == "39.99"
    assert res.json()["currency"] == "USD"


def test_gbp_catalog_pledge_order_payload(api):
    client, spy = api
    pid = project_id_for_product("K6gupx4")
    res = client.post(
        "/api/escales/pledges",
        json={
            "amount_eur": "114.00",
            "description": "HX210E VHF",
            "milestone_id": "",
            "kind": "project_pledge",
            "target_id": pid,
        },
    )
    assert res.status_code == 200
    assert spy.orders[-1]["currency_code"] == "GBP"
    assert spy.orders[-1]["amount_eur"] == "114.00"


def test_eur_catalog_pledge_order_payload(api):
    client, spy = api
    pid = project_id_for_product("zRl9jHd")
    res = client.post(
        "/api/escales/pledges",
        json={
            "amount_eur": "20.00",
            "description": "Dry bag",
            "milestone_id": "",
            "kind": "project_pledge",
            "target_id": pid,
        },
    )
    assert res.status_code == 200
    assert spy.orders[-1]["currency_code"] == "EUR"
    assert spy.orders[-1]["amount_eur"] == "20.00"


def test_jpy_catalog_pledge_whole_units(api, monkeypatch):
    client, spy = api

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
    res = client.post(
        "/api/escales/pledges",
        json={
            "amount_eur": "1200",
            "description": "JPY gear",
            "milestone_id": "",
            "kind": "project_pledge",
            "target_id": "gear-c3-jpy1",
        },
    )
    assert res.status_code == 200
    assert spy.orders[-1]["currency_code"] == "JPY"
    assert spy.orders[-1]["amount_eur"] == "1200"
    assert "." not in spy.orders[-1]["amount_eur"]


def test_usd_funded_pct_uses_native_captures_only(api):
    client, _ = api
    pid = project_id_for_product("QE0Vp6a")

    async def _seed():
        await record_finance(
            "pledge_captured",
            amount_eur="26.39",
            currency="USD",
            milestone_id="projet",
            target_id=pid,
            pledge_kind="project_pledge",
        )
        await record_finance(
            "pledge_captured",
            amount_eur="100.00",
            currency="EUR",
            milestone_id="projet",
            target_id=pid,
            pledge_kind="project_pledge",
        )

    asyncio.run(_seed())
    body = client.get(f"/api/escales/channel3/catalog/by-project/{pid}/fund").json()
    assert body["funded_currency"] == "USD"
    assert body["funded_amount_minor"] == 2639
    assert body["funded_pct"] == 33


def test_unsupported_catalog_currency_rejected(api, monkeypatch):
    client, spy = api

    def _fake_lookup(project_id: str):
        return {
            "channel3_product_id": "bad",
            "project_id": project_id,
            "price_currency": "XXX",
            "price_amount_minor": 100,
            "unit_price_amount_minor": 100,
            "catalog_default_target_amount_minor": 100,
            "catalog_default_target_currency": "XXX",
        }

    monkeypatch.setattr("app.channel3_catalog.lookup_catalog_by_project_id", _fake_lookup)
    res = client.post(
        "/api/escales/pledges",
        json={
            "amount_eur": "1.00",
            "description": "Bad currency",
            "milestone_id": "",
            "kind": "project_pledge",
            "target_id": "gear-c3-bad",
        },
    )
    assert res.status_code == 422
    assert "not support" in res.text.lower()
    assert not spy.orders


class AuthorizeSpy(CaptureOrderSpy):
    def create_authorize_order(self, amount_eur, description, reference_id, idempotency_key=None, **kwargs):
        self.orders.append({"amount_eur": amount_eur, "currency_code": kwargs.get("currency_code")})
        order_id = f"ORD-A-{len(self.orders)}"
        return {
            "id": order_id,
            "status": "CREATED",
            "links": [{"rel": "approve", "href": f"https://sandbox.paypal.com/checkout?token={order_id}"}],
        }


def test_eur_stop_pledge_stays_eur(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-05-15T08:00:00Z")
    reset_ledger()
    spy = AuthorizeSpy()

    async def _run():
        doc = await create_pledge(
            amount_eur="25.00",
            description="Stop pledge",
            milestone_id="dep-lorient",
            kind="mile",
            client=spy,
        )
        assert doc["currency"] == "EUR"
        assert spy.orders[0].get("currency_code") in (None, "EUR")

    asyncio.run(_run())
