"""PayPal webhook ingestion: signature verification and idempotent processing."""
from __future__ import annotations

import base64
import binascii
import json
import logging
from typing import Any, Optional
from urllib.parse import urlsplit

from .config import paypal_webhook_id, simulated_now, zapiper_enabled
from .ledger import get_ledger, now_iso, pledge_defaults, record_finance, record_webhook_outcome
from .paypal_client import PayPalClient, PayPalError

log = logging.getLogger("escales.webhooks")


class WebhookRejected(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(detail)


# A pending capture moves only on these events. An authorized pledge stays put.
_PENDING_CAPTURE = {
    "PAYMENT.CAPTURE.COMPLETED": "captured",
    "PAYMENT.CAPTURE.DENIED": "capture_failed",
    "PAYMENT.CAPTURE.PENDING": "pending",
    "PAYMENT.CAPTURE.REFUNDED": "refunded",
}

_AUDITED_EVENTS = frozenset({
    "VAULT.PAYMENT-TOKEN.CREATED",
    "VAULT.PAYMENT-TOKEN.DELETED",
    "PAYMENT.AUTHORIZATION.CREATED",
    "PAYMENT.AUTHORIZATION.VOIDED",
    "PAYMENT.CAPTURE.COMPLETED",
    "PAYMENT.CAPTURE.DENIED",
    "PAYMENT.CAPTURE.REFUNDED",
    "PAYMENT.CAPTURE.PENDING",
    "CHECKOUT.ORDER.APPROVED",
    "CUSTOMER.DISPUTE.CREATED",
    "CUSTOMER.DISPUTE.UPDATED",
    "CUSTOMER.DISPUTE.RESOLVED",
    "INVOICING.INVOICE.PAID",
    "INVOICING.INVOICE.CANCELLED",
    "INVOICING.INVOICE.CREATED",
    "INVOICING.INVOICE.SCHEDULED",
    "INVOICING.INVOICE.UPDATED",
    "BILLING.SUBSCRIPTION.ACTIVATED",
    "BILLING.SUBSCRIPTION.CANCELLED",
    "BILLING.SUBSCRIPTION.CREATED",
    "BILLING.SUBSCRIPTION.SUSPENDED",
    "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
    "PAYMENT.CAPTURE.REVERSED",
    "PAYMENT.REFUND.COMPLETED",
    "PAYMENT.SALE.COMPLETED",
    "PAYMENT.PAYOUTSBATCH.PROCESSING",
    "PAYMENT.PAYOUTSBATCH.SUCCESS",
    "PAYMENT.PAYOUTSBATCH.DENIED",
})


class WebhookDuplicate(Exception):
    """Same PayPal event id (or transmission id) was already accepted."""

    def __init__(self, transmission_id: str):
        self.transmission_id = transmission_id
        super().__init__(transmission_id)


def _header(headers: Any, name: str) -> str:
    """Read a PayPal transmission header (ASGI lowercases names)."""
    if hasattr(headers, "get"):
        direct = headers.get(name)
        if direct:
            return str(direct).strip()
        lowered = headers.get(name.lower())
        if lowered:
            return str(lowered).strip()
    return ""


def _transmission_headers(headers: Any) -> dict[str, str]:
    """All five PayPal webhook transmission headers required for verify."""
    keys = (
        "PAYPAL-TRANSMISSION-ID",
        "PAYPAL-TRANSMISSION-TIME",
        "PAYPAL-TRANSMISSION-SIG",
        "PAYPAL-CERT-URL",
        "PAYPAL-AUTH-ALGO",
    )
    return {key: _header(headers, key) for key in keys}


def _verification_log_fields(
    verification: Optional[dict] = None,
    exc: Optional[PayPalError] = None,
) -> dict[str, str]:
    """Safe fields for logs and treasurer webhook audit (no secrets)."""
    fields: dict[str, str] = {}
    for source in (verification,):
        if not isinstance(source, dict):
            continue
        status = str(source.get("verification_status") or "").strip()
        if status:
            fields["verification_status"] = status[:64]
        for key in ("name", "message"):
            value = source.get(key)
            if value:
                fields[key] = str(value)[:200]
    if exc is not None and exc.body:
        try:
            body = json.loads(exc.body) if isinstance(exc.body, str) else exc.body
        except (TypeError, json.JSONDecodeError):
            body = None
        if isinstance(body, dict):
            status = str(body.get("verification_status") or "").strip()
            if status and "verification_status" not in fields:
                fields["verification_status"] = status[:64]
            for key in ("name", "message"):
                value = body.get(key)
                if value and key not in fields:
                    fields[key] = str(value)[:200]
    return fields


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

    tx = _transmission_headers(headers)
    transmission_id = tx["PAYPAL-TRANSMISSION-ID"]
    transmission_time = tx["PAYPAL-TRANSMISSION-TIME"]
    transmission_sig = tx["PAYPAL-TRANSMISSION-SIG"]
    cert_url = tx["PAYPAL-CERT-URL"]
    auth_algo = tx["PAYPAL-AUTH-ALGO"]

    if not all(tx.values()):
        missing = [key for key, value in tx.items() if not value]
        log.warning("PayPal webhook missing headers: %s", ",".join(missing))
        raise WebhookRejected(400, "PayPal webhook headers are incomplete")
    if _signature_is_malformed(transmission_sig):
        raise WebhookRejected(400, "PayPal webhook signature is malformed")
    if _cert_url_is_malformed(cert_url):
        raise WebhookRejected(400, "PayPal webhook certificate URL is malformed")

    try:
        event = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebhookRejected(400, "Webhook body must be JSON") from exc

    body_for_verify = raw_body.lstrip(b"\xef\xbb\xbf")

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
            raw_event=body_for_verify,
        )
    except PayPalError as exc:
        detail_fields = _verification_log_fields(None, exc)
        log.warning(
            "PayPal webhook verify-webhook-signature HTTP error status=%s fields=%s",
            exc.status,
            detail_fields,
        )
        await _record_outcome(transmission_id, event, "rejected", None, extra=detail_fields)
        rejected = _rejected_signature_status(exc)
        reason = detail_fields.get("verification_status") or detail_fields.get("message") or "rejected"
        if rejected:
            raise WebhookRejected(
                rejected,
                f"PayPal webhook signature or certificate was rejected ({reason})",
            ) from exc
        raise WebhookRejected(502, f"PayPal signature verification failed ({reason})") from exc

    status = (verification.get("verification_status") or "").upper()
    if status != "SUCCESS":
        detail_fields = _verification_log_fields(verification, None)
        log.warning("PayPal webhook verification_status=%s fields=%s", status, detail_fields)
        await _record_outcome(transmission_id, event, "rejected", None, extra=detail_fields)
        reason = detail_fields.get("verification_status") or status or "FAILURE"
        raise WebhookRejected(401, f"PayPal webhook signature rejected ({reason})")

    dedup_key = _dedup_key(event, transmission_id)
    ledger = get_ledger()
    if await ledger.has_webhook(dedup_key):
        pledge_id = await _pledge_id_for(event)
        await _record_outcome(transmission_id, event, "duplicate", pledge_id)
        raise WebhookDuplicate(transmission_id)

    result = await _apply_event(event)
    claimed = await ledger.claim_webhook(
        dedup_key,
        {"event_id": event.get("id") if isinstance(event, dict) else None,
         "event_type": event.get("event_type") if isinstance(event, dict) else None,
         "transmission_id": transmission_id},
    )
    if not claimed:
        pledge_id = result.get("pledge_id") or await _pledge_id_for(event)
        await _record_outcome(transmission_id, event, "duplicate", pledge_id)
        raise WebhookDuplicate(transmission_id)
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
    ledger = get_ledger()
    pledge = await ledger.find_pledge_by_order_id(order_id) if order_id else None
    if pledge is None:
        capture_id = _capture_id_from_resource(resource)
        if capture_id:
            pledge = await ledger.find_pledge_by_capture_id(capture_id)
    if event_type == "VAULT.PAYMENT-TOKEN.DELETED":
        from .pledges import find_pledge_by_vault_id, mark_vault_token_deleted_for_vault_id

        vault_token_id = str(resource.get("id") or "").strip()
        if vault_token_id:
            if pledge or await find_pledge_by_vault_id(vault_token_id):
                await mark_vault_token_deleted_for_vault_id(vault_token_id)
            if pledge is None:
                pledge = await find_pledge_by_vault_id(vault_token_id)

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
    if event_type in _AUDITED_EVENTS:
        await record_finance(
            "webhook_event",
            event_type=event_type,
            order_id=order_id,
            pledge_id=pledge.get("_id") if pledge else None,
            resource_id=resource.get("id"),
            status=resource.get("status"),
        )
    if event_type == "VAULT.PAYMENT-TOKEN.CREATED" and pledge:
        vault_token_id = str(resource.get("id") or "").strip()
        if vault_token_id and pledge.get("vault_on_purchase") and not pledge.get("vault_id"):
            pledge["vault_id"] = vault_token_id
        pledge["history"] = list(pledge.get("history") or []) + ["webhook_vault_token_created"]
        pledge = await get_ledger().save_pledge(pledge)
    if event_type == "VAULT.PAYMENT-TOKEN.DELETED" and pledge:
        if pledge.get("vault_token_deleted") is not True:
            pledge["vault_token_deleted"] = True
        pledge["history"] = list(pledge.get("history") or []) + ["webhook_vault_token_deleted"]
        pledge = await get_ledger().save_pledge(pledge)
    if event_type == "PAYMENT.AUTHORIZATION.CREATED" and pledge and pledge.get("status") == "created":
        auth_id = resource.get("id")
        if auth_id and not pledge.get("authorization_id"):
            pledge["authorization_id"] = str(auth_id)
            pledge = await get_ledger().save_pledge(pledge)
    if event_type == "PAYMENT.AUTHORIZATION.VOIDED" and pledge:
        pledge["history"] = list(pledge.get("history") or []) + ["webhook_authorization_voided"]
        if str(pledge.get("status") or "") in {"authorized", "created", "vaulted"}:
            pledge["status"] = "voided"
            if not str(pledge.get("voided_at") or "").strip():
                pledge["voided_at"] = simulated_now().replace(microsecond=0).isoformat()
        pledge = await get_ledger().save_pledge(pledge)
    if event_type == "CHECKOUT.ORDER.APPROVED" and pledge:
        pledge["history"] = list(pledge.get("history") or []) + ["webhook_order_approved"]
        pledge = await get_ledger().save_pledge(pledge)
    target = _PENDING_CAPTURE.get(event_type)
    if pledge and target:
        status = str(pledge.get("status") or "")
        mode = str(pledge.get("payment_mode") or pledge.get("intent") or "")
        allowed = {"pending"}
        if target == "captured" and mode == "CAPTURE":
            allowed = allowed | {"created"}
        if status in allowed:
            pledge["status"] = target
            pledge["paypal_status"] = "COMPLETED" if target == "captured" else "DENIED"
            if resource.get("id"):
                pledge["capture_id"] = str(resource["id"])
            if target == "captured" and not str(pledge.get("captured_at") or "").strip():
                pledge["captured_at"] = simulated_now().replace(microsecond=0).isoformat()
            pledge["history"] = list(pledge.get("history") or []) + [target]
            pledge = await get_ledger().save_pledge(pledge)
            if target == "captured":
                from .pledges import record_pledge_captured_once

                await record_pledge_captured_once(pledge, actor="webhook")
            else:
                await record_finance(
                    "webhook_capture_denied",
                    event_type=event_type,
                    order_id=order_id,
                    pledge_id=pledge.get("_id"),
                    resource_id=resource.get("id"),
                    milestone_id=pledge.get("milestone_id"),
                    amount_eur=pledge.get("amount_eur"),
                    status=target,
                    pledge_kind=identity.get("kind") if identity else None,
                    target_id=identity.get("target_id") if identity else None,
                )

    if event_type == "PAYMENT.CAPTURE.REFUNDED" and pledge and pledge.get("status") in {
        "captured",
        "partially_refunded",
        "refunded",
    }:
        from .pledges import reconcile_refund_on_pledge

        refund_id = str(resource.get("id") or "").strip()
        amount = resource.get("amount") if isinstance(resource.get("amount"), dict) else {}
        amount_eur = str(amount.get("value") or pledge.get("amount_eur") or "0")
        status = str(resource.get("status") or "COMPLETED").upper()
        if refund_id:
            pledge = await reconcile_refund_on_pledge(
                pledge,
                refund_id=refund_id,
                amount_eur=amount_eur,
                status=status,
            )
        pledge["history"] = list(pledge.get("history") or []) + ["webhook_refunded"]
        pledge = await get_ledger().save_pledge(pledge)
        await record_finance(
            "webhook_capture_refunded",
            pledge_id=pledge.get("_id"),
            capture_id=_capture_id_from_resource(resource) or resource.get("id"),
            refund_id=refund_id or None,
        )

    if event_type.startswith("CUSTOMER.DISPUTE."):
        dispute_id = str(resource.get("dispute_id") or resource.get("id") or "")
        if dispute_id and await _dispute_resource_known_to_ledger(resource):
            await record_finance(
                "paypal_dispute_snapshot",
                dispute_id=dispute_id,
                source="webhook",
                status=resource.get("status"),
                payload=resource,
            )

    if event_type.startswith("INVOICING.INVOICE."):
        invoice_id = str(resource.get("id") or resource.get("invoice_id") or "")
        status = "PAID" if event_type.endswith(".PAID") else resource.get("status")
        if invoice_id:
            await record_finance(
                "paypal_invoice_webhook",
                invoice_id=invoice_id,
                event_type=event_type,
                status=status,
            )

    if event_type.startswith("BILLING.SUBSCRIPTION.") or event_type == "PAYMENT.SALE.COMPLETED":
        from .paypal_subscriptions import record_subscription, subscription_known_locally

        sub_id, plan_id, status = _subscription_webhook_fields(event_type, resource)
        if sub_id and await subscription_known_locally(sub_id):
            await record_subscription(
                subscription_id=sub_id,
                plan_id=plan_id,
                status=status,
            )

    if event_type.startswith("PAYMENT.PAYOUTSBATCH."):
        header = resource.get("batch_header") if isinstance(resource.get("batch_header"), dict) else {}
        batch_id = str(header.get("payout_batch_id") or resource.get("batch_header") or resource.get("id") or "")
        await record_finance(
            "payout_batch_webhook",
            event_type=event_type,
            batch_id=batch_id,
            status=resource.get("batch_status"),
        )

    return {
        "accepted": True,
        "pledge_id": pledge.get("_id") if pledge else None,
        "order_id": order_id,
    }


def _dedup_key(event: dict, transmission_id: str) -> str:
    """Claim the PayPal event id. A transmission id is only the fallback."""
    event_id = str(event.get("id") or "").strip() if isinstance(event, dict) else ""
    return event_id or transmission_id


def _event_dict(event: Any) -> dict:
    return event if isinstance(event, dict) else {}


def _subscription_webhook_fields(event_type: str, resource: dict) -> tuple[str, str, str]:
    """Return subscription id, plan id, and normalized status for billing webhooks."""
    if event_type == "PAYMENT.SALE.COMPLETED":
        sub_id = str(
            resource.get("billing_agreement_id")
            or resource.get("subscription_id")
            or ""
        ).strip()
        if not sub_id:
            return "", "", ""
        plan_id = str(resource.get("plan_id") or "")
        status = str(resource.get("state") or resource.get("status") or "ACTIVE")
        return sub_id, plan_id, status
    if not event_type.startswith("BILLING.SUBSCRIPTION."):
        return "", "", ""
    sub_id = str(resource.get("id") or "").strip()
    plan_id = str(resource.get("plan_id") or "")
    suffix = event_type.split(".")[-1].upper()
    status = str(resource.get("status") or suffix)
    return sub_id, plan_id, status


def _resource_id(event: Any) -> Optional[str]:
    resource = _event_dict(event).get("resource")
    if isinstance(resource, dict) and resource.get("id"):
        return str(resource["id"])
    return None


async def _dispute_resource_known_to_ledger(resource: dict) -> bool:
    """True when the dispute references a capture or order we already track."""
    return await _pledge_for_dispute_resource(resource) is not None


async def _pledge_for_dispute_resource(resource: dict) -> Optional[dict]:
    if not isinstance(resource, dict):
        return None
    ledger = get_ledger()
    order_id = _order_id_from_resource(resource)
    if order_id:
        found = await ledger.find_pledge_by_order_id(order_id)
        if found:
            return found
    capture_id = _capture_id_from_resource(resource)
    if capture_id:
        found = await ledger.find_pledge_by_capture_id(capture_id)
        if found:
            return found
    disputed = resource.get("disputed_transactions")
    if isinstance(disputed, list):
        for txn in disputed:
            if not isinstance(txn, dict):
                continue
            for key in ("seller_transaction_id", "buyer_transaction_id", "transaction_id"):
                token = str(txn.get(key) or "").strip()
                if not token:
                    continue
                found = await ledger.find_pledge_by_capture_id(token)
                if found:
                    return found
    return None


async def _pledge_id_for(event: Any) -> Optional[str]:
    resource = _event_dict(event).get("resource")
    resource = resource if isinstance(resource, dict) else {}
    order_id = _order_id_from_resource(resource)
    ledger = get_ledger()
    if order_id:
        pledge = await ledger.find_pledge_by_order_id(order_id)
        if pledge:
            return pledge.get("_id")
    capture_id = _capture_id_from_resource(resource)
    if capture_id:
        pledge = await ledger.find_pledge_by_capture_id(capture_id)
        return pledge.get("_id") if pledge else None
    return None


async def _record_outcome(
    transmission_id: str,
    event: Any,
    outcome: str,
    pledge_id: Optional[str],
    *,
    extra: Optional[dict] = None,
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
    if extra:
        for key, value in extra.items():
            if value is not None and str(value).strip():
                row[key] = str(value)[:200]
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


def _capture_id_from_resource(resource: dict) -> Optional[str]:
    """Capture id on a CAPTURE or REFUND webhook resource.

    Refund payloads often omit ``order_id``; the parent capture id is in
    ``supplementary_data.related_ids`` or a ``/v2/payments/captures/`` link.
    """
    if not isinstance(resource, dict) or not resource:
        return None
    supplementary = resource.get("supplementary_data") or {}
    if isinstance(supplementary, dict):
        related = supplementary.get("related_ids") or {}
        if isinstance(related, dict) and related.get("capture_id"):
            return str(related["capture_id"])
    capture_marker = "/v2/payments/captures/"
    for link in resource.get("links") or []:
        href = str(link.get("href") or "")
        if capture_marker in href:
            segment = href.split(capture_marker, 1)[1].split("/")[0].strip()
            if segment:
                return segment
    resource_id = str(resource.get("id") or "").strip()
    status = str(resource.get("status") or "").upper()
    if resource_id and status in {"COMPLETED", "REFUNDED", "PARTIALLY_REFUNDED"}:
        for link in resource.get("links") or []:
            href = str(link.get("href") or "")
            if str(link.get("rel") or "").lower() == "self" and capture_marker in href:
                return resource_id
        if status == "REFUNDED" and not _order_id_from_resource(resource):
            return resource_id
    return None


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
