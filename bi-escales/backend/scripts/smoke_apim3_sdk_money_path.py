#!/usr/bin/env python3
"""Sandbox smoke for the APIM-3 PayPal Server SDK money path.

Reads PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET from the environment.
Refuses any PayPal host other than https://api-m.sandbox.paypal.com.
Prints ids and statuses only. Does not print credentials or response bodies.

Run from bi-escales/backend with the repo virtualenv:

    python scripts/smoke_apim3_sdk_money_path.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.escales.config import SANDBOX_BASE, EscalesConfig  # noqa: E402
from app.escales.paypal_client import (  # noqa: E402
    PayPalClient,
    PayPalError,
    _paypal_api_error_fields,
)
from app.escales.paypal_sdk_gateway import build_sandbox_client, install_client  # noqa: E402

# Public PayPal sandbox test Visa. Expiry is 2028-12.
_TEST_CARD = {
    "number": "4005519200000004",
    "expiry": "2028-12",
    "security_code": "123",
    "name": "Escales Smoke",
}
_RETURN = "https://example.com/escales/return"
_CANCEL = "https://example.com/escales/cancel"

_step = "start"


def _emit(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")


def _fail(exc: BaseException | None = None) -> None:
    status = getattr(exc, "status", None) if exc is not None else None
    name: str | None = None
    if isinstance(exc, PayPalError):
        fields = _paypal_api_error_fields(exc.body)
        if isinstance(fields, dict):
            raw = fields.get("name")
            name = str(raw) if raw else None
    elif exc is not None:
        name = type(exc).__name__
    http_status = status if isinstance(status, int) else None
    _emit({"step": _step, "http_status": http_status, "name": name})
    raise SystemExit(1)


def _key() -> str:
    return uuid.uuid4().hex


def _refuse_non_sandbox() -> None:
    """Reject a live PayPal host before any credential or HTTP call."""
    global _step
    _step = "sandbox_guard"
    env_name = (os.environ.get("PAYPAL_ENV") or "sandbox").strip().lower()
    if env_name != "sandbox":
        _fail()
    for key, value in os.environ.items():
        upper = key.upper()
        if not any(token in upper for token in ("URL", "BASE", "HOST", "PAYPAL_ENV")):
            continue
        lowered = value.strip().lower().rstrip("/")
        if not lowered or "paypal.com" not in lowered:
            continue
        if lowered == SANDBOX_BASE or lowered.startswith(SANDBOX_BASE + "/"):
            continue
        if "sandbox.paypal.com" in lowered:
            continue
        if "api-m.paypal.com" in lowered or "://api.paypal.com" in lowered:
            _fail()


def _require_credentials() -> tuple[str, str]:
    global _step
    _step = "credentials"
    client_id = (os.environ.get("PAYPAL_CLIENT_ID") or "").strip()
    client_secret = (os.environ.get("PAYPAL_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        _fail()
    return client_id, client_secret


def _pin_sandbox_sdk() -> PayPalClient:
    global _step
    _step = "sdk_pin"
    os.environ["PAYPAL_ENV"] = "sandbox"
    os.environ["ESCALES_PAYPAL_SDK_ENABLED"] = "1"
    client_id, client_secret = _require_credentials()
    client = PayPalClient(EscalesConfig(client_id, client_secret))
    if client.cfg.base_url.rstrip("/") != SANDBOX_BASE or client.cfg.env != "sandbox":
        _fail()
    sdk = build_sandbox_client()
    base = str(sdk.config.get_base_uri()).rstrip("/")
    environment = str(getattr(sdk.config, "environment", ""))
    if base != SANDBOX_BASE or "PRODUCTION" in environment.upper():
        _fail()
    install_client(sdk)
    return client


def _authorization(order: dict[str, Any]) -> tuple[str, str]:
    for unit in order.get("purchase_units") or []:
        if not isinstance(unit, dict):
            continue
        payments = unit.get("payments") if isinstance(unit.get("payments"), dict) else {}
        for auth in payments.get("authorizations") or []:
            if isinstance(auth, dict) and auth.get("id"):
                return str(auth["id"]), str(auth.get("status") or "")
    raise PayPalError(502, "authorization id missing")


def _capture_id(payload: dict[str, Any]) -> tuple[str, str]:
    if payload.get("id") and not payload.get("purchase_units"):
        return str(payload["id"]), str(payload.get("status") or "")
    for unit in payload.get("purchase_units") or []:
        if not isinstance(unit, dict):
            continue
        payments = unit.get("payments") if isinstance(unit.get("payments"), dict) else {}
        for cap in payments.get("captures") or []:
            if isinstance(cap, dict) and cap.get("id"):
                return str(cap["id"]), str(cap.get("status") or "")
    raise PayPalError(502, "capture id missing")


def _create_card_order(client: PayPalClient, intent: str, amount: str) -> dict[str, Any]:
    body = {
        "intent": intent,
        "purchase_units": [{
            "amount": {"currency_code": "EUR", "value": amount},
        }],
        "payment_source": {"card": dict(_TEST_CARD)},
    }
    return client._req("POST", "/v2/checkout/orders", body, idempotency_key=_key())


def _authorize(client: PayPalClient, order_id: str) -> dict[str, Any]:
    try:
        return client.authorize_order(order_id)
    except PayPalError as exc:
        fields = _paypal_api_error_fields(exc.body)
        issues = []
        if isinstance(fields, dict):
            for item in fields.get("details") or []:
                if isinstance(item, dict) and item.get("issue"):
                    issues.append(str(item["issue"]))
        if exc.status == 422 and "ORDER_ALREADY_AUTHORIZED" in issues:
            return client.get_order(order_id)
        raise


def main() -> None:
    global _step
    logging.disable(logging.CRITICAL)
    _refuse_non_sandbox()
    client = _pin_sandbox_sdk()

    _step = "authorize_capture"
    created = _create_card_order(client, "AUTHORIZE", "10.00")
    order_id = str(created.get("id") or "")
    authorized = _authorize(client, order_id)
    auth_id, auth_status = _authorization(authorized if authorized.get("purchase_units") else created)
    if not auth_status:
        auth_status = str(authorized.get("status") or "")
    captured = client.capture_authorization(auth_id, idempotency_key=_key())
    capture_id, capture_status = _capture_id(captured)

    _step = "refund"
    refunded = client.refund_capture(
        capture_id,
        amount_eur="10.00",
        idempotency_key=_key(),
    )

    _step = "authorize_void"
    void_order = _create_card_order(client, "AUTHORIZE", "10.00")
    void_order_id = str(void_order.get("id") or "")
    void_authorized = _authorize(client, void_order_id)
    void_auth_id, _void_auth_status = _authorization(
        void_authorized if void_authorized.get("purchase_units") else void_order,
    )
    voided = client.void_authorization(void_auth_id)

    _step = "vault_setup_token"
    setup = client.create_setup_token(
        _RETURN,
        _CANCEL,
        customer_id="escales-smoke",
        idempotency_key=_key(),
    )

    _step = "subscription"
    product = client.create_billing_product(
        name="Escales smoke supporter",
        description="Sandbox smoke subscription for Blue Intelligence Escales",
        idempotency_key=_key(),
    )
    plan = client.create_billing_plan(
        product_id=str(product.get("id") or ""),
        name="Escales smoke monthly",
        amount_eur="5.00",
        interval_unit="MONTH",
        idempotency_key=_key(),
    )
    subscription = client.create_billing_subscription(
        plan_id=str(plan.get("id") or ""),
        return_url=_RETURN,
        cancel_url=_CANCEL,
        idempotency_key=_key(),
        locale="en-US",
    )

    _emit({
        "authorize_capture": {
            "order_id": order_id,
            "authorization_id": auth_id,
            "authorization_status": auth_status,
            "capture_id": capture_id,
            "capture_status": capture_status,
        },
        "authorize_void": {
            "order_id": void_order_id,
            "authorization_id": void_auth_id,
            "void_id": voided.get("id"),
            "void_status": voided.get("status"),
        },
        "vault_setup_token": {
            "id": setup.get("id"),
            "status": setup.get("status"),
        },
        "refund": {
            "id": refunded.get("id"),
            "status": refunded.get("status"),
        },
        "subscription": {
            "id": subscription.get("id"),
            "status": subscription.get("status"),
        },
    })


if __name__ == "__main__":
    try:
        main()
    except PayPalError as exc:
        _fail(exc)
    except SystemExit:
        raise
    except Exception as exc:
        _fail(exc)
