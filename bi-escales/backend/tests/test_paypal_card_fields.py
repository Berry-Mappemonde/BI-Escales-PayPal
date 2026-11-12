"""Card Fields checkout: card payment_source on orders and vault setup tokens."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.config import EscalesConfig, card_sca_method
from app.escales.paypal_client import PayPalClient
from app.escales.pledges import create_pledge, reset_ledger


class Spy:
    def __init__(self):
        self.calls: list[tuple] = []

    def create_authorize_order(self, **kwargs):
        self.calls.append(("wallet-order", kwargs))
        return {"id": "ORDER-W", "links": [{"rel": "approve", "href": "https://sandbox.paypal.com/w"}]}

    def create_card_authorize_order(self, **kwargs):
        self.calls.append(("card-order", kwargs))
        return {"id": "ORDER-C", "links": [{"rel": "approve", "href": "https://sandbox.paypal.com/c"}]}

    def create_setup_token(self, *args, **kwargs):
        self.calls.append(("wallet-setup", args, kwargs))
        return {"id": "SETUP-W", "links": [{"rel": "approve", "href": "https://sandbox.paypal.com/sw"}]}

    def create_card_setup_token(self, **kwargs):
        self.calls.append(("card-setup", kwargs))
        return {"id": "SETUP-C", "links": [{"rel": "approve", "href": "https://sandbox.paypal.com/sc"}]}


def test_create_card_authorize_order_sends_sca():
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"id": "ORD1", "status": "CREATED", "intent": "AUTHORIZE"})

    client = PayPalClient(
        EscalesConfig("cid", "sec"),
        transport=httpx.MockTransport(handler),
    )
    client.create_card_authorize_order(
        "12.00",
        "12 miles",
        "ref1",
        return_url="https://example.com/r",
        cancel_url="https://example.com/c",
    )
    card = bodies[0]["payment_source"]["card"]
    assert card["attributes"]["verification"]["method"] == "SCA_WHEN_REQUIRED"
    assert card["experience_context"]["user_action"] == "CONTINUE"


def test_create_capture_order_uses_pay_now():
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"id": "CAP1", "status": "CREATED", "intent": "CAPTURE"})

    client = PayPalClient(
        EscalesConfig("cid", "sec"),
        transport=httpx.MockTransport(handler),
    )
    client.create_capture_order(
        "10.00", "Common fund", "fund-1",
        return_url="https://example.com/r", cancel_url="https://example.com/c",
    )
    client.create_capture_order(
        "10.00", "Card donation", "fund-2", checkout_method="card",
        return_url="https://example.com/r", cancel_url="https://example.com/c",
    )
    assert bodies[0]["payment_source"]["paypal"]["experience_context"]["user_action"] == "PAY_NOW"
    assert bodies[1]["payment_source"]["card"]["experience_context"]["user_action"] == "PAY_NOW"


def test_card_sca_always_is_sandbox_only(monkeypatch):
    monkeypatch.setenv("ESCALES_CARD_SCA_ALWAYS", "1")
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"id": "ORD-SCA", "status": "CREATED", "intent": "AUTHORIZE"})

    client = PayPalClient(EscalesConfig("cid", "sec"), transport=httpx.MockTransport(handler))
    client.create_card_authorize_order(
        "12.00", "12 miles", "ref-sca",
        return_url="https://example.com/r", cancel_url="https://example.com/c",
    )
    assert bodies[0]["payment_source"]["card"]["attributes"]["verification"]["method"] == "SCA_ALWAYS"
    monkeypatch.setenv("PAYPAL_ENV", "live")
    assert card_sca_method() == "SCA_WHEN_REQUIRED"


def test_create_card_setup_token_sends_sca():
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"id": "ST1", "status": "APPROVED"})

    client = PayPalClient(
        EscalesConfig("cid", "sec"),
        transport=httpx.MockTransport(handler),
    )
    client.create_card_setup_token(
        "https://example.com/r",
        "https://example.com/c",
        customer_id="cust-1",
    )
    card = bodies[0]["payment_source"]["card"]
    assert card["attributes"]["verification"]["method"] == "SCA_WHEN_REQUIRED"


def test_card_checkout_requires_flag(monkeypatch):
    monkeypatch.delenv("ESCALES_CARD_FIELDS_ENABLED", raising=False)
    reset_ledger()

    async def noop(_draft):
        return None

    monkeypatch.setattr("app.escales.departure_clock.refuse_early_authorization", noop)

    async def body():
        spy = Spy()
        with pytest.raises(ValueError, match="card checkout is disabled"):
            await create_pledge(
                amount_eur="5.00",
                description="5 miles",
                milestone_id="dep-mayotte",
                client=spy,
                checkout_method="card",
            )

    asyncio.run(body())
    reset_ledger()


def test_card_authorize_pledge_uses_card_order(monkeypatch):
    monkeypatch.setenv("ESCALES_CARD_FIELDS_ENABLED", "1")
    reset_ledger()

    async def noop(_draft):
        return None

    monkeypatch.setattr("app.escales.departure_clock.refuse_early_authorization", noop)

    async def body():
        spy = Spy()
        doc = await create_pledge(
            amount_eur="5.00",
            description="5 miles",
            milestone_id="dep-mayotte",
            client=spy,
            checkout_method="card",
        )
        assert doc["checkout_method"] == "card"
        assert doc["order_id"] == "ORDER-C"
        assert spy.calls[0][0] == "card-order"

    asyncio.run(body())
    reset_ledger()
