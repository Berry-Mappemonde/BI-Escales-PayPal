"""Platform fees apply to marina berth orders only when enabled."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.config import EscalesConfig
from app.escales.paypal_client import PayPalClient
from app.escales.pledges import create_pledge, reset_ledger


def test_purchase_unit_platform_fees_shape():
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"id": "ORD-B", "status": "CREATED"})

    client = PayPalClient(EscalesConfig("cid", "sec"), transport=httpx.MockTransport(handler))
    client.create_authorize_order(
        "30.00",
        "berth",
        "ref-berth",
        payee_merchant_id="SELLER1",
        platform_fee_eur="3.00",
        platform_merchant_id="PLATFORM1",
    )
    unit = bodies[0]["purchase_units"][0]
    assert unit["payee"]["merchant_id"] == "SELLER1"
    fees = unit["payment_instruction"]["platform_fees"]
    assert fees[0]["amount"]["value"] == "3.00"
    assert fees[0]["payee"]["merchant_id"] == "PLATFORM1"


@pytest.mark.parametrize("kind", ["mile", "project_pledge", "common_fund"])
def test_non_berth_skips_platform_fees(monkeypatch, kind):
    monkeypatch.setenv("ESCALES_PLATFORM_FEES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_PLATFORM_PAYEE_MERCHANT_ID", "PLATFORM1")
    monkeypatch.setenv("ESCALES_MARINA_SELLER_MERCHANT_ID", "SELLER1")
    reset_ledger()

    class Spy:
        def __init__(self):
            self.bodies: list[dict] = []

        def create_authorize_order(self, **kwargs):
            self.bodies.append(kwargs)
            return {"id": "ORD1", "links": [{"rel": "approve", "href": "https://sandbox.paypal.com/x"}]}

        def create_capture_order(self, **kwargs):
            return {"id": "ORDC", "links": []}

    async def noop(_draft):
        return None

    monkeypatch.setattr("app.escales.departure_clock.refuse_early_authorization", noop)

    async def body():
        spy = Spy()
        kwargs = dict(
            amount_eur="5.00" if kind != "project_pledge" else "15.00",
            description="test",
            milestone_id="" if kind in {"project_pledge", "common_fund"} else "dep-mayotte",
            client=spy,
            kind=kind,
            target_id="projet" if kind == "project_pledge" else ("fonds-commun" if kind == "common_fund" else "dep-mayotte"),
        )
        await create_pledge(**kwargs)
        if spy.bodies:
            assert "platform_fee_eur" not in spy.bodies[0]
            assert "payee_merchant_id" not in spy.bodies[0]

    asyncio.run(body())
    reset_ledger()
