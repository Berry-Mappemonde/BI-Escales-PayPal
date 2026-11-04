"""PayPal webhook ingestion: signature verification and idempotent processing."""
from __future__ import annotations

import json
from typing import Any, Optional

from .config import paypal_webhook_id, zapiper_enabled
from .ledger import get_ledger, pledge_defaults, record_finance
from .paypal_client import PayPalClient, PayPalError


class WebhookRejected(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(detail)


class WebhookDuplicate(Exception):
    """Same PayPal transmission_id was already accepted."""

    def __init__(self, transmission_id: str):
        self.transmission_id = transmission_id
        super().__init__(transmission_id)


def _header(headers: Any, name: str) -> str:
    value = headers.get(name) or headers.get(name.lower()) or ""
    return str(value).strip()


async def verify_and_process(
    *,
    raw_body: bytes,
    headers: Any,
    client: PayPalClient,
) -> dict:
    webhook_id = paypal_webhook_id()
    if not webhook_id:
        raise WebhookRejected(503, "PAYPAL_WEBHOOK_ID is not configured")

    transmission_id = _header(headers, "PAYPAL-TRANSMISSION-ID")
    transmission_time = _header(headers, "PAYPAL-TRANSMISSION-TIME")
    transmission_sig = _header(headers, "PAYPAL-TRANSMISSION-SIG")
    cert_url = _header(headers, "PAYPAL-CERT-URL")
    auth_algo = _header(headers, "PAYPAL-AUTH-ALGO")

    if not all([transmission_id, transmission_time, transmission_sig, cert_url, auth_algo]):
        raise WebhookRejected(400, "PayPal webhook headers are incomplete")

    ledger = get_ledger()
    if await ledger.has_webhook(transmission_id):
        raise WebhookDuplicate(transmission_id)

    try:
        event = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebhookRejected(400, "Webhook body must be JSON") from exc

    try:
        verification = client.verify_webhook_signature(
            auth_algo=auth_algo,
            cert_url=cert_url,
            transmission_id=transmission_id,
            transmission_sig=transmission_sig,
            transmission_time=transmission_time,
            webhook_id=webhook_id,
            webhook_event=event,
        )
    except PayPalError as exc:
        raise WebhookRejected(502, "PayPal signature verification failed") from exc

    status = (verification.get("verification_status") or "").upper()
    if status != "SUCCESS":
        raise WebhookRejected(401, "PayPal webhook signature rejected")

    claimed = await ledger.claim_webhook(
        transmission_id,
        {"event_id": event.get("id"), "event_type": event.get("event_type")},
    )
    if not claimed:
        raise WebhookDuplicate(transmission_id)

    result = await _apply_event(event)
    result["transmission_id"] = transmission_id
    result["event_id"] = event.get("id")
    result["event_type"] = event.get("event_type")
    if zapiper_enabled():
        result["zapier_hint"] = "forward this payload to your Zapier catch hook if configured"
    return result


async def _apply_event(event: dict) -> dict:
    event_type = event.get("event_type") or ""
    resource = event.get("resource") or {}
    order_id = _order_id_from_resource(resource)
    pledge = await get_ledger().find_pledge_by_order_id(order_id) if order_id else None

    identity = pledge_defaults(pledge) if pledge else None
    await record_finance(
        "webhook_received",
        event_type=event_type,
        order_id=order_id,
        pledge_id=pledge.get("_id") if pledge else None,
        resource_id=resource.get("id"),
        pledge_kind=identity.get("kind") if identity else None,
        target_id=identity.get("target_id") if identity else None,
    )

    return {
        "accepted": True,
        "pledge_id": pledge.get("_id") if pledge else None,
        "order_id": order_id,
    }


def _order_id_from_resource(resource: dict) -> Optional[str]:
    if not resource:
        return None
    for key in ("supplementary_data",):
        block = resource.get(key) or {}
        related = block.get("related_ids") or {}
        order_id = related.get("order_id")
        if order_id:
            return str(order_id)
    for key in ("order_id", "custom_id"):
        value = resource.get(key)
        if value:
            return str(value)
    links = resource.get("links") or []
    for link in links:
        href = link.get("href") or ""
        if "/v2/checkout/orders/" in href:
            segment = href.rstrip("/").split("/")[-1]
            if segment:
                return segment
    return None
