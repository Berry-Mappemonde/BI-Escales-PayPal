"""PayPal webhook ingestion: signature verification and idempotent processing."""
from __future__ import annotations

import json
from typing import Any, Optional

from .config import paypal_webhook_id, zapiper_enabled
from .ledger import get_ledger, record_finance
from .paypal_client import PayPalClient, PayPalError


class WebhookRejected(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(detail)


class WebhookDuplicate(Exception):
    """Same PayPal event id was already accepted."""

    def __init__(self, transmission_id: str):
        self.transmission_id = transmission_id
        super().__init__(transmission_id)


# PayPal event → pledge status, and the capture/authorization status we store.
_EVENT_STATUS = {
    "PAYMENT.AUTHORIZATION.VOIDED": ("voided", "VOIDED"),
    "PAYMENT.CAPTURE.COMPLETED": ("settled", "COMPLETED"),
    "PAYMENT.CAPTURE.DENIED": ("failed", "DENIED"),
    "PAYMENT.CAPTURE.PENDING": ("pending", "PENDING"),
}


def _header(headers: Any, name: str) -> str:
    value = headers.get(name) or headers.get(name.lower()) or ""
    return str(value).strip()


def _dedup_key(event: dict, transmission_id: str) -> str:
    event_id = str(event.get("id") or "").strip()
    return event_id or transmission_id


def _webhook_may_update(current: str, target: str) -> bool:
    if current in {"voided", "failed", "settled"}:
        return False
    if target == "voided":
        return current in {"created", "authorized", "vaulted", "pending"}
    if target == "pending":
        return current in {"created", "authorized", "vaulted"}
    if target in {"settled", "failed"}:
        return current in {"created", "authorized", "vaulted", "pending", "captured"}
    return False


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

    try:
        event = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebhookRejected(400, "Webhook body must be JSON") from exc
    if not isinstance(event, dict):
        raise WebhookRejected(400, "Webhook body must be a JSON object")

    dedup_key = _dedup_key(event, transmission_id)
    ledger = get_ledger()
    if await ledger.has_webhook(dedup_key):
        raise WebhookDuplicate(transmission_id)

    try:
        verification = client.verify_webhook_signature(
            auth_algo=auth_algo,
            cert_url=cert_url,
            transmission_id=transmission_id,
            transmission_sig=transmission_sig,
            transmission_time=transmission_time,
            webhook_id=webhook_id,
            webhook_event=event,
            raw_event=raw_body,
        )
    except PayPalError as exc:
        raise WebhookRejected(502, "PayPal signature verification failed") from exc

    status = (verification.get("verification_status") or "").upper()
    if status != "SUCCESS":
        raise WebhookRejected(401, "PayPal webhook signature rejected")

    if await ledger.has_webhook(dedup_key):
        raise WebhookDuplicate(transmission_id)

    result = await _apply_event(event)
    claimed = await ledger.claim_webhook(
        dedup_key,
        {
            "event_id": event.get("id"),
            "event_type": event.get("event_type"),
            "transmission_id": transmission_id,
        },
    )
    if not claimed:
        raise WebhookDuplicate(transmission_id)

    result["transmission_id"] = transmission_id
    result["event_id"] = event.get("id")
    result["event_type"] = event.get("event_type")
    if zapiper_enabled():
        result["zapier_hint"] = "forward this payload to your Zapier catch hook if configured"
    return result


async def _apply_event(event: dict) -> dict:
    event_type = event.get("event_type") or ""
    resource = event.get("resource") or {}
    if not isinstance(resource, dict):
        resource = {}
    pledge, order_id = await _locate_pledge(event_type, resource)
    updated = False
    mapped = _EVENT_STATUS.get(event_type)
    if pledge and mapped:
        target, paypal_status = mapped
        current = str(pledge.get("status") or "")
        if _webhook_may_update(current, target):
            pledge["status"] = target
            pledge["paypal_status"] = paypal_status
            pledge["history"] = list(pledge.get("history") or []) + [target]
            if event_type.startswith("PAYMENT.CAPTURE."):
                capture_id = resource.get("id")
                if capture_id:
                    pledge["capture_id"] = str(capture_id)
            pledge["webhook_event_id"] = event.get("id")
            pledge = await get_ledger().save_pledge(pledge)
            updated = True

    await record_finance(
        "webhook_received",
        event_type=event_type,
        order_id=order_id,
        pledge_id=pledge.get("_id") if pledge else None,
        resource_id=resource.get("id"),
        pledge_status=pledge.get("status") if pledge else None,
        updated=updated,
    )

    return {
        "accepted": True,
        "pledge_id": pledge.get("_id") if pledge else None,
        "order_id": order_id,
        "pledge_status": pledge.get("status") if pledge else None,
        "updated": updated,
    }


async def _locate_pledge(event_type: str, resource: dict) -> tuple[Optional[dict], Optional[str]]:
    ledger = get_ledger()
    order_id = _order_id_from_resource(resource)
    if order_id:
        found = await ledger.find_pledge_by_order_id(order_id)
        if found:
            return found, order_id
    auth_id = _authorization_id(event_type, resource)
    if auth_id:
        found = await ledger.find_pledge_by_authorization_id(auth_id)
        if found:
            return found, order_id or found.get("order_id")
    return None, order_id


def _authorization_id(event_type: str, resource: dict) -> Optional[str]:
    related = (resource.get("supplementary_data") or {}).get("related_ids") or {}
    auth_id = related.get("authorization_id")
    if auth_id:
        return str(auth_id)
    if event_type.startswith("PAYMENT.AUTHORIZATION."):
        value = resource.get("id")
        return str(value) if value else None
    return None


def _order_id_from_resource(resource: dict) -> Optional[str]:
    if not resource:
        return None
    block = resource.get("supplementary_data") or {}
    related = block.get("related_ids") or {}
    order_id = related.get("order_id")
    if order_id:
        return str(order_id)
    value = resource.get("order_id")
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
