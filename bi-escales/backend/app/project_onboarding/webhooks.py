"""MERCHANT.ONBOARDING.COMPLETED webhook handling for project onboarding."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.escales.config import paypal_webhook_id, webhooks_enabled
from app.escales.paypal_client import PayPalClient, PayPalError
from app.escales.webhooks import WebhookRejected, _transmission_headers, _signature_is_malformed, _cert_url_is_malformed
from app.project_onboarding.service import mark_onboarded_from_webhook
from app.project_onboarding.store import claim_webhook_event

log = logging.getLogger("escales.project_onboarding.webhooks")


async def verify_merchant_onboarding_webhook(
    *,
    raw_body: bytes,
    headers: Any,
    client: PayPalClient,
) -> dict:
    if not webhooks_enabled():
        raise WebhookRejected(404, "webhooks disabled")
    webhook_id = paypal_webhook_id()
    if not webhook_id:
        raise WebhookRejected(503, "PAYPAL_WEBHOOK_ID is not configured")
    tx = _transmission_headers(headers)
    if not all(tx.values()):
        raise WebhookRejected(400, "PayPal webhook headers are incomplete")
    if _signature_is_malformed(tx["PAYPAL-TRANSMISSION-SIG"]):
        raise WebhookRejected(401, "Invalid webhook signature")
    if _cert_url_is_malformed(tx["PAYPAL-CERT-URL"]):
        raise WebhookRejected(400, "Invalid cert url")
    try:
        verification = client.verify_webhook_signature(
            transmission_id=tx["PAYPAL-TRANSMISSION-ID"],
            transmission_time=tx["PAYPAL-TRANSMISSION-TIME"],
            cert_url=tx["PAYPAL-CERT-URL"],
            auth_algo=tx["PAYPAL-AUTH-ALGO"],
            transmission_sig=tx["PAYPAL-TRANSMISSION-SIG"],
            webhook_id=webhook_id,
            event_body=raw_body,
        )
    except PayPalError as exc:
        raise WebhookRejected(exc.status, "Webhook verification failed") from exc
    status = str((verification or {}).get("verification_status") or "").upper()
    if status != "SUCCESS":
        raise WebhookRejected(401, "Webhook verification failed")
    try:
        event = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebhookRejected(400, "Invalid JSON") from exc
    return await process_merchant_onboarding_event(event)


async def process_merchant_onboarding_event(event: dict) -> dict:
    event_type = str(event.get("event_type") or "")
    if event_type != "MERCHANT.ONBOARDING.COMPLETED":
        return {"ignored": True, "event_type": event_type}
    event_id = str(event.get("id") or "").strip()
    if event_id and not await claim_webhook_event(event_id):
        return {"duplicate": True, "event_id": event_id}
    resource = event.get("resource") if isinstance(event.get("resource"), dict) else {}
    tracking_id = str(resource.get("tracking_id") or resource.get("partner_client_id") or "").strip()
    merchant_id = str(resource.get("merchant_id") or resource.get("merchant_id_in_paypal") or "").strip()
    if not tracking_id:
        return {"accepted": False, "reason": "missing_tracking_id"}
    outcome = await mark_onboarded_from_webhook(tracking_id, merchant_id=merchant_id)
    return {"accepted": True, **outcome, "event_id": event_id or None}
