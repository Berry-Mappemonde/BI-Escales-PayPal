"""Marina berth capture: platform fee retained + net paid to marina via PayPal Payouts."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from .config import marina_payouts_enabled, paypal_berth_platform_fees_on_order, platform_fee_eur
from .ledger import get_ledger, list_finance_entries, now_iso, record_finance, update_finance_entry
from .marina_payout_email import resolve_marina_payout_email_sync
from .paypal_client import PayPalError, _paypal_api_error_fields


def _money(raw: object) -> Decimal:
    try:
        return Decimal(str(raw or "0").strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def order_carried_platform_fees(pledge: dict) -> bool:
    """True only when this pledge's PayPal order paid the marina directly (multiparty)."""
    if "platform_fees_on_order" in pledge:
        return bool(pledge.get("platform_fees_on_order"))
    # Older rows: card and vault orders were never built with platform_fees.
    if str(pledge.get("checkout_method") or "").strip().lower() == "card":
        return False
    if pledge.get("vault_on_purchase") or pledge.get("vault_id"):
        return False
    return paypal_berth_platform_fees_on_order(str(pledge.get("target_id") or ""))


def should_settle_marina_berth_capture(pledge: dict) -> bool:
    if str(pledge.get("kind") or "").strip().lower() != "berth":
        return False
    if order_carried_platform_fees(pledge):
        return False
    if marina_payouts_enabled():
        return True
    # Fallback: multiparty is configured for this marina but the order (card / vault)
    # could not carry platform_fees, so the marina is paid by Payouts instead.
    return paypal_berth_platform_fees_on_order(str(pledge.get("target_id") or ""))


_SETTLED_STATUSES = {"skipped_zero_net", "pending", "processing", "success", "sent", "new"}


def marina_settlement_done(pledge: dict) -> bool:
    """Nothing left to retry: not a settled berth, or payout already sent / not needed."""
    if not should_settle_marina_berth_capture(pledge):
        return True
    if pledge.get("marina_payout_batch_id"):
        return True
    return str(pledge.get("marina_payout_status") or "") in _SETTLED_STATUSES


def split_berth_capture_amount(amount_eur: str) -> tuple[str, str]:
    total = _money(amount_eur)
    fee = min(_money(platform_fee_eur()), total)
    net = total - fee
    return f"{fee:.2f}", f"{net:.2f}"


def marina_payout_batch_id(pledge: dict) -> str:
    pledge_id = str(pledge.get("_id") or "")
    capture_id = str(pledge.get("capture_id") or "").strip()
    token = capture_id or pledge_id
    return f"marina-payout-{pledge_id}-{token}"[:127]


async def _fee_recorded(pledge_id: str) -> bool:
    for entry in await list_finance_entries():
        if entry.get("kind") == "marina_platform_fee" and entry.get("pledge_id") == pledge_id:
            return True
    return False


async def _payout_sent_entry(pledge_id: str) -> Optional[dict]:
    for entry in await list_finance_entries():
        if entry.get("kind") == "marina_payout_sent" and entry.get("pledge_id") == pledge_id:
            return entry
    return None


def _payout_status_from_webhook(event_type: str, batch_status: Optional[str]) -> str:
    token = str(batch_status or "").strip().upper()
    if token:
        return token.lower()
    suffix = str(event_type or "").split(".")[-1].upper()
    if suffix == "SUCCESS":
        return "success"
    if suffix == "PROCESSING":
        return "processing"
    if suffix == "DENIED":
        return "denied"
    return "processing"


async def apply_payout_batch_webhook(
    *,
    batch_id: str,
    event_type: str,
    batch_status: Optional[str] = None,
) -> None:
    wanted = str(batch_id or "").strip()
    if not wanted:
        return
    status = _payout_status_from_webhook(event_type, batch_status)
    for entry in await list_finance_entries():
        if entry.get("kind") != "marina_payout_sent":
            continue
        if str(entry.get("payout_batch_id") or "") != wanted:
            continue
        await update_finance_entry(
            str(entry.get("_id") or ""),
            {"status": status, "webhook_event": event_type},
        )
        pledge_id = str(entry.get("pledge_id") or "")
        if not pledge_id:
            continue
        pledge = await get_ledger().get_pledge(pledge_id)
        if not pledge:
            continue
        pledge["marina_payout_status"] = status
        pledge["marina_payout_batch_id"] = wanted
        await get_ledger().save_pledge(pledge)


async def _record_fee_once(fee: str, shared: dict) -> None:
    if await _fee_recorded(str(shared.get("pledge_id") or "")):
        return
    await record_finance(
        "marina_platform_fee",
        amount_eur=fee,
        status="retained",
        description="Platform fee retained on berth capture",
        **shared,
    )


async def apply_marina_berth_settlement(
    pledge: dict,
    *,
    actor: str,
    client: Optional[Any] = None,
) -> dict:
    """Pay the marina its net, then retain the platform fee.

    Retry-safe: the fee line is written only once the payout went out (or the net is
    zero), so a failed or pending payout can be retried by the next capture/webhook
    call. ``sender_batch_id`` is deterministic, so PayPal deduplicates a resend.
    """
    if not should_settle_marina_berth_capture(pledge):
        return pledge
    pledge_id = str(pledge.get("_id") or "")
    if not pledge_id:
        return pledge

    from .pledges import _identity, finance_milestone_id

    fee, net = split_berth_capture_amount(str(pledge.get("amount_eur") or "0"))
    pledge["platform_fee_eur"] = fee
    pledge["marina_net_eur"] = net
    pledge["platform_fee_simulated"] = False
    at = str(pledge.get("captured_at") or "").strip() or now_iso()
    milestone_id = finance_milestone_id(pledge)
    shared = {
        "pledge_id": pledge_id,
        "milestone_id": milestone_id,
        "currency": pledge.get("currency") or "EUR",
        "actor": actor,
        "at": at,
        "pledge_kind": "berth",
        "target_id": pledge.get("target_id"),
        **_identity(pledge),
    }

    existing = await _payout_sent_entry(pledge_id)
    if existing:
        pledge["marina_payout_batch_id"] = existing.get("payout_batch_id") or pledge.get("marina_payout_batch_id")
        pledge["marina_payout_status"] = existing.get("status") or "sent"
        pledge.pop("marina_payout_error", None)
        await _record_fee_once(fee, shared)
        return pledge

    net_amount = _money(net)
    if net_amount <= 0:
        pledge["marina_payout_status"] = "skipped_zero_net"
        await _record_fee_once(fee, shared)
        return pledge

    receiver = resolve_marina_payout_email_sync(pledge)
    pledge["marina_payout_receiver"] = receiver or None
    if not receiver:
        pledge["marina_payout_status"] = "pending_email"
        return pledge
    if client is None or not hasattr(client, "create_payout"):
        pledge["marina_payout_status"] = "pending_client"
        return pledge

    batch_id = marina_payout_batch_id(pledge)
    note = f"Escales marina berth net ({pledge_id[:8]})"
    try:
        payload = client.create_payout(
            batch_id=batch_id,
            receiver_email=receiver,
            amount_eur=f"{net_amount:.2f}",
            note=note,
            item_id=pledge_id,
        )
    except PayPalError as exc:
        err = _paypal_api_error_fields(exc.body) or {}
        pledge["marina_payout_status"] = "failed"
        pledge["marina_payout_error"] = err
        await record_finance(
            "marina_payout_failed",
            amount_eur=f"{net_amount:.2f}",
            receiver_email=receiver,
            status="failed",
            sender_batch_id=batch_id,
            paypal_error=err,
            **shared,
        )
        return pledge

    batch_header = payload.get("batch_header") if isinstance(payload, dict) else {}
    batch_header = batch_header if isinstance(batch_header, dict) else {}
    payout_batch_id = str(batch_header.get("payout_batch_id") or "").strip()
    batch_status = str(batch_header.get("batch_status") or "PENDING").lower()
    pledge["marina_payout_batch_id"] = payout_batch_id or None
    pledge["marina_payout_status"] = batch_status or "sent"
    pledge.pop("marina_payout_error", None)
    await record_finance(
        "marina_payout_sent",
        amount_eur=f"{net_amount:.2f}",
        receiver_email=receiver,
        payout_batch_id=payout_batch_id,
        sender_batch_id=batch_id,
        status=pledge["marina_payout_status"],
        **shared,
    )
    await _record_fee_once(fee, shared)
    return pledge
