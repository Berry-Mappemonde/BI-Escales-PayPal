"""PayPal webhook ingestion: signature verification and idempotent processing."""
from __future__ import annotations

import base64
import binascii
import json
from typing import Any, Optional
from urllib.parse import urlsplit

from .config import paypal_webhook_id, zapiper_enabled
from .ledger import get_ledger, now_iso, pledge_defaults, record_finance, record_webhook_outcome
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


def _signature_is_malformed(signature: str) -> bool:
    """A transmission signature is base64. Anything else is a client error."""
    try:
        raw = base64.b64decode(signature, validate=True)
    except (binascii.Error, ValueError):
        return True
    return not raw


def _cert_url_is_malformed(cert_url: str) -> bool:
    """PayPal publishes the webhook cert on paypal.com over https."""
    parts = urlsplit(cert_url)
    host = (parts.hostname or "").lower()
    paypal = host == "paypal.com" or host.endswith(".paypal.com")
    return parts.scheme != "https" or not paypal or not parts.path


def _rejected_signature_status(exc: PayPalError) -> Optional[int]:
    """PayPal 400/401 on a bad signature or cert stays 400/401, not 502."""
    if exc.status in {400, 401}:
        return exc.status
    blob = f"{exc} {exc.body}".upper()
    if "SIGNATURE" in blob:
        return 401
    if "CERT" in blob:
        return 400
    return None


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
    if _signature_is_malformed(transmission_sig):
        raise WebhookRejected(400, "PayPal webhook signature is malformed")
    if _cert_url_is_malformed(cert_url):
        raise WebhookRejected(400, "PayPal webhook certificate URL is malformed")

    try:
        event = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebhookRejected(400, "Webhook body must be JSON") from exc

    # Signature first. A replay of a known transmission_id with a bad
    # signature is a rejection, not a duplicate.
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
        await _record_outcome(transmission_id, event, "rejected", None)
        rejected = _rejected_signature_status(exc)
        if rejected:
            raise WebhookRejected(rejected, "PayPal webhook signature or certificate was rejected") from exc
        raise WebhookRejected(502, "PayPal signature verification failed") from exc

    status = (verification.get("verification_status") or "").upper()
    if status != "SUCCESS":
        await _record_outcome(transmission_id, event, "rejected", None)
        raise WebhookRejected(401, "PayPal webhook signature rejected")

    ledger = get_ledger()
    claimed = await ledger.claim_webhook(
        transmission_id,
        {"event_id": event.get("id") if isinstance(event, dict) else None,
         "event_type": event.get("event_type") if isinstance(event, dict) else None},
    )
    if not claimed:
        pledge_id = await _pledge_id_for(event)
        await _record_outcome(transmission_id, event, "duplicate", pledge_id)
        raise WebhookDuplicate(transmission_id)

    result = await _apply_event(event)
    await _record_outcome(transmission_id, event, "accepted", result.get("pledge_id"))
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
    if (
        pledge
        and event_type == "PAYMENT.CAPTURE.COMPLETED"
        and pledge.get("status") == "pending"
    ):
        pledge["status"] = "captured"
        pledge["paypal_status"] = "COMPLETED"
        if resource.get("id"):
            pledge["capture_id"] = str(resource["id"])
        pledge["history"] = list(pledge.get("history") or []) + ["captured"]
        pledge = await get_ledger().save_pledge(pledge)
        from .pledges import record_pledge_captured_once

        await record_pledge_captured_once(pledge, actor="webhook")

    return {
        "accepted": True,
        "pledge_id": pledge.get("_id") if pledge else None,
        "order_id": order_id,
    }


def _event_dict(event: Any) -> dict:
    return event if isinstance(event, dict) else {}


def _resource_id(event: Any) -> Optional[str]:
    resource = _event_dict(event).get("resource")
    if isinstance(resource, dict) and resource.get("id"):
        return str(resource["id"])
    return None


async def _pledge_id_for(event: Any) -> Optional[str]:
    resource = _event_dict(event).get("resource")
    order_id = _order_id_from_resource(resource if isinstance(resource, dict) else {})
    if not order_id:
        return None
    pledge = await get_ledger().find_pledge_by_order_id(order_id)
    return pledge.get("_id") if pledge else None


async def _record_outcome(
    transmission_id: str,
    event: Any,
    outcome: str,
    pledge_id: Optional[str],
) -> None:
    body = _event_dict(event)
    row = {
        "transmission_id": transmission_id,
        "event_type": body.get("event_type"),
        "resource_id": _resource_id(body),
        "pledge_id": pledge_id,
        "time": now_iso(),
        "outcome": outcome,
    }
    await record_webhook_outcome(row)
    if pledge_id and outcome in {"accepted", "duplicate"}:
        await _append_pledge_webhook(pledge_id, row)


async def _append_pledge_webhook(pledge_id: str, row: dict) -> None:
    ledger = get_ledger()
    doc = await ledger.get_pledge(pledge_id)
    if not doc:
        return
    events = list(doc.get("webhook_events") or [])
    transmission_id = row.get("transmission_id")
    if transmission_id and any(
        event.get("transmission_id") == transmission_id for event in events
    ):
        return
    events.append(
        {
            "transmission_id": row.get("transmission_id"),
            "event_type": row.get("event_type"),
            "resource_id": row.get("resource_id"),
            "time": row.get("time"),
            "outcome": row.get("outcome"),
        }
    )
    doc["webhook_events"] = events
    await ledger.save_pledge(doc)


def _order_id_from_resource(resource: dict) -> Optional[str]:
    """Order id on an ORDER, AUTHORIZATION, or CAPTURE resource.

    Authorization and capture payloads keep it at
    ``supplementary_data.related_ids.order_id``.
    """
    if not isinstance(resource, dict) or not resource:
        return None
    supplementary = resource.get("supplementary_data") or {}
    if isinstance(supplementary, dict):
        related = supplementary.get("related_ids") or {}
        if isinstance(related, dict) and related.get("order_id"):
            return str(related["order_id"])
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
