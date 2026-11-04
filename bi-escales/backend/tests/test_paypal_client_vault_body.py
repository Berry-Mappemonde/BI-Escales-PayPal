"""PayPal client: Vault setup body, purchase metadata, idempotency."""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.escales.config import vault_cancel_url, vault_return_url
from app.escales.paypal_client import PayPalClient, SOFT_DESCRIPTOR, VAULT_BRAND_NAME
from app.escales.config import EscalesConfig


def test_no_example_com_in_escales_tree():
    root = Path(__file__).resolve().parents[2]
    for rel in ("backend/app/escales/config.py", "render.yaml"):
        text = (root / rel).read_text(encoding="utf-8")
        assert "example.com/escales" not in text
        assert "https://example.com" not in text


def test_vault_default_urls_use_render_service():
    assert "bi-escales-api.onrender.com" in vault_return_url()
    assert vault_return_url().endswith("?vault=return")
    assert vault_cancel_url().endswith("?vault=cancel")


def test_setup_token_includes_usage_pattern_and_customer():
    bodies: list[dict] = []

    def handler(request: httpx.Request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        bodies.append(json.loads(request.content))
        assert request.headers.get("PayPal-Request-Id", "").startswith("setup-token-")
        return httpx.Response(201, json={"id": "SETUP1", "links": []})

    client = PayPalClient(
        EscalesConfig("cid", "secret"),
        transport=httpx.MockTransport(handler),
    )
    client.create_setup_token(
        "https://bi-escales-api.onrender.com/?vault=return&pledge_id=p1",
        "https://bi-escales-api.onrender.com/?vault=cancel&pledge_id=p1",
        customer_id="sponsor-abc",
    )
    body = bodies[0]
    assert body["customer"] == {"id": "sponsor-abc"}
    paypal = body["payment_source"]["paypal"]
    assert paypal["usage_pattern"] == "UNSCHEDULED_POSTPAID"
    assert paypal["permit_multiple_payment_tokens"] is False
    assert paypal["experience_context"]["brand_name"] == VAULT_BRAND_NAME
    assert paypal["experience_context"]["shipping_preference"] == "NO_SHIPPING"


def test_authorize_order_includes_custom_id_and_descriptor():
    bodies: list[dict] = []

    def handler(request: httpx.Request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        bodies.append(json.loads(request.content))
        assert request.headers.get("PayPal-Request-Id") == "order-pledge-42"
        return httpx.Response(201, json={"id": "ORD1", "status": "CREATED"})

    client = PayPalClient(
        EscalesConfig("cid", "secret"),
        transport=httpx.MockTransport(handler),
    )
    client.create_authorize_order("5.00", "miles", "pledge-42", idempotency_key="order-pledge-42")
    unit = bodies[0]["purchase_units"][0]
    assert unit["custom_id"] == "pledge-42"
    assert unit["invoice_id"] == "pledge-42"
    assert unit["soft_descriptor"] == SOFT_DESCRIPTOR
