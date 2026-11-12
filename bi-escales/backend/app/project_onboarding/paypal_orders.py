"""CAPTURE orders with unlinked payee email for onboard-after-payment."""

from __future__ import annotations

import os
from typing import Any, Optional

from app.escales.config import (
    order_cancel_url, order_return_url, platform_credentials_active,
    load_platform_config, paypal_sdk_reads_enabled, SANDBOX_BASE,
)
from app.escales.paypal_client import PayPalClient, PayPalError, approve_link
from app.escales.paypal_idempotency import paypal_request_id


def bn_code_header() -> dict[str, str]:
    code = (os.environ.get("ESCALES_PAYPAL_BN_CODE") or os.environ.get("PAYPAL_BN_CODE") or "").strip()
    if code:
        return {"PayPal-Partner-Attribution-Id": code}
    return {}



def _platform_sdk(client: PayPalClient) -> Any:
    """Cache on the onboarding HTTP client; never read/install the merchant SDK."""
    from app.escales.paypal_sdk_gateway import build_sandbox_client

    cfg = load_platform_config() if platform_credentials_active() else client.cfg
    if cfg.env != "sandbox" or cfg.base_url.rstrip("/") != SANDBOX_BASE:
        raise ValueError("Onboarding SDK is sandbox only")
    sdk = getattr(client, "_onboarding_server_sdk", None)
    if sdk is None:
        sdk = build_sandbox_client(client_id=cfg.client_id, client_secret=cfg.client_secret)
        client._onboarding_server_sdk = sdk
    return sdk


def _sdk_order_call(client: PayPalClient, operation: str, options: dict) -> dict:
    from app.escales.paypal_sdk_gateway import _execute

    return _execute("orders", operation, options, sdk=_platform_sdk(client))


def create_unlinked_payee_capture_order(
    client: PayPalClient,
    *,
    amount_eur: str,
    description: str,
    project_id: str,
    payee_email: str,
    donation_id: str,
    return_url: str,
    cancel_url: str,
    checkout_locale: Optional[str] = None,
) -> dict:
    body = {
        "intent": "CAPTURE",
        "payment_source": {
            "paypal": {
                "experience_context": client._experience_context(
                    return_url or order_return_url(),
                    cancel_url or order_cancel_url(),
                    locale=checkout_locale,
                ),
            },
        },
        "purchase_units": [
            {
                "reference_id": donation_id[:256],
                "description": str(description or "")[:127],
                "custom_id": str(project_id)[:127],
                "amount": {
                    "currency_code": client.cfg.currency,
                    "value": amount_eur,
                },
                "payee": {"email_address": payee_email},
            }
        ],
    }
    idem = paypal_request_id(donation_id, "onboard-capture-order")[:127]
    if paypal_sdk_reads_enabled():
        from paypalserversdk.models.order_request import OrderRequest
        return _sdk_order_call(client, "create_order", {
            "body": OrderRequest(**body), "paypal_request_id": idem,
            "prefer": "return=representation",
            "paypal_partner_attribution_id": bn_code_header().get("PayPal-Partner-Attribution-Id"),
        })
    hdrs = {
        "Authorization": f"Bearer {client._access_token()}",
        "Content-Type": "application/json",
        "PayPal-Request-Id": idem,
        "Prefer": "return=representation",
        **bn_code_header(),
    }
    response = client._request_with_retry("POST", "/v2/checkout/orders", json=body, headers=hdrs)
    if response.status_code >= 400:
        from app.escales.paypal_client import PayPalError

        raise PayPalError(response.status_code, response.text)
    return response.json() if response.content else {}


def read_order(client: PayPalClient, order_id: str) -> dict:
    """Read with the isolated Platform SDK, or the existing Platform HTTP path.

    Neither selection uses the process-wide merchant SDK token.
    """
    if paypal_sdk_reads_enabled():
        return _sdk_order_call(client, "get_order", {"id": order_id})
    if platform_credentials_active():
        return client._req("GET", f"/v2/checkout/orders/{order_id}")
    return client.get_order(order_id)


def capture_order_once(client: PayPalClient, order_id: str) -> dict:
    idem = paypal_request_id(order_id, "onboard-capture")
    if paypal_sdk_reads_enabled():
        from paypalserversdk.models.order_capture_request import OrderCaptureRequest
        return _sdk_order_call(client, "capture_order", {
            "id": order_id, "body": OrderCaptureRequest(),
            "paypal_request_id": idem, "prefer": "return=representation",
        })
    return client._req("POST", f"/v2/checkout/orders/{order_id}/capture", {}, idempotency_key=idem)


def order_belongs_to_donation(order: dict, donation: dict) -> bool:
    """True when PayPal order metadata matches a donation row from this app."""
    donation_id = str(donation.get("_id") or "")
    project_id = str(donation.get("project_id") or "")
    stored_order_id = str(donation.get("order_id") or "")
    paypal_order_id = str(order.get("id") or "")
    if stored_order_id and paypal_order_id and stored_order_id != paypal_order_id:
        return False
    units = order.get("purchase_units") or []
    if not units or not isinstance(units[0], dict):
        return bool(stored_order_id and stored_order_id == paypal_order_id)
    unit = units[0]
    ref = str(unit.get("reference_id") or "")
    custom = str(unit.get("custom_id") or "")
    if ref and donation_id and ref != donation_id:
        return False
    if custom and project_id and custom != project_id:
        return False
    return True


def order_approve_url(order: dict) -> str:
    return approve_link(order)


def capture_status_and_id(payload: dict) -> tuple[str, Optional[str]]:
    for unit in payload.get("purchase_units") or []:
        payments = (unit or {}).get("payments") or {}
        for cap in payments.get("captures") or []:
            if isinstance(cap, dict):
                return str(cap.get("status") or "").upper(), cap.get("id")
    status = str(payload.get("status") or "").upper()
    return status, None


def is_unlinked_payee_failure(exc: Exception) -> bool:
    from app.escales.paypal_client import PayPalError

    if not isinstance(exc, PayPalError):
        return False
    if exc.status in {422, 500}:
        return True
    blob = str(exc.body or "").upper()
    return "UNLINKED" in blob or "PAYEE" in blob
