"""PayPal capture/refund settlement fields from seller receivable/payable breakdowns.

FX comes only from PayPal response fields — no external rate source.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

logger = logging.getLogger(__name__)


def capture_resource_from_payload(payload: dict) -> Optional[dict]:
    """Return the nested or bare capture object from an order/capture API response."""
    if not isinstance(payload, dict):
        return None
    for unit in payload.get("purchase_units") or []:
        if not isinstance(unit, dict):
            continue
        for cap in (unit.get("payments") or {}).get("captures") or []:
            if isinstance(cap, dict):
                return cap
    status = str(payload.get("status") or "").upper()
    if payload.get("id") and status in {"COMPLETED", "PENDING", "DECLINED", "FAILED"}:
        return payload
    return None


def _money_part(raw: Any) -> Optional[dict[str, str]]:
    if not isinstance(raw, dict):
        return None
    value = str(raw.get("value") or "").strip()
    currency = str(raw.get("currency_code") or raw.get("currency") or "").strip().upper()
    if not value or not currency:
        return None
    return {"currency": currency, "value": value}


def _decimal_text(value: str) -> Optional[Decimal]:
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _format_eur(amount: Decimal) -> str:
    return f"{amount.quantize(Decimal('0.01')):.2f}"


def parse_seller_receivable_breakdown(capture: dict) -> Optional[dict[str, Any]]:
    """Parse PayPal ``seller_receivable_breakdown`` from a capture resource."""
    if not isinstance(capture, dict):
        return None
    breakdown = capture.get("seller_receivable_breakdown")
    if not isinstance(breakdown, dict):
        return None
    gross = _money_part(breakdown.get("gross_amount"))
    fee = _money_part(breakdown.get("paypal_fee"))
    net = _money_part(breakdown.get("net_amount"))
    receivable = _money_part(breakdown.get("receivable_amount"))
    rate_raw = breakdown.get("exchange_rate")
    exchange_rate: Optional[dict[str, str]] = None
    if isinstance(rate_raw, dict):
        source = str(rate_raw.get("source_currency") or "").strip().upper()
        target = str(rate_raw.get("target_currency") or "").strip().upper()
        rate_value = str(rate_raw.get("value") or "").strip()
        if source and target and rate_value:
            exchange_rate = {
                "source_currency": source,
                "target_currency": target,
                "value": rate_value,
            }
    if not gross and not net:
        return None
    out: dict[str, Any] = {}
    if gross:
        out["gross_amount"] = gross
    if fee:
        out["paypal_fee"] = fee
    if net:
        out["net_amount"] = net
    if receivable:
        out["receivable_amount"] = receivable
    if exchange_rate:
        out["exchange_rate"] = exchange_rate
    return out or None


def parse_seller_payable_breakdown(refund: dict) -> Optional[dict[str, str]]:
    """EUR net reversal from ``seller_payable_breakdown.net_amount`` on a refund."""
    if not isinstance(refund, dict):
        return None
    breakdown = refund.get("seller_payable_breakdown")
    if not isinstance(breakdown, dict):
        return None
    net = _money_part(breakdown.get("net_amount"))
    if not net:
        return None
    if str(net.get("currency") or "").upper() != "EUR":
        logger.warning(
            "PayPal refund seller_payable_breakdown net_amount is not EUR (%s)",
            net.get("currency"),
        )
        return None
    return net


def _eur_capture_without_breakdown(pledge: dict, capture: Optional[dict]) -> Optional[str]:
    """Legacy EUR: amount minus PayPal fee on the capture when breakdown is missing."""
    pledge_ccy = str(pledge.get("currency") or "EUR").strip().upper()
    if pledge_ccy != "EUR":
        return None
    gross = _decimal_text(str(pledge.get("amount_eur") or "0"))
    if gross is None:
        return None
    fee = Decimal("0")
    if isinstance(capture, dict):
        fee_part = capture.get("seller_receivable_breakdown")
        if isinstance(fee_part, dict):
            fee_money = _money_part(fee_part.get("paypal_fee"))
            if fee_money:
                parsed = _decimal_text(fee_money["value"])
                if parsed is not None:
                    fee = parsed
        elif capture.get("paypal_fee"):
            fee_money = _money_part(capture.get("paypal_fee"))
            if fee_money:
                parsed = _decimal_text(fee_money["value"])
                if parsed is not None:
                    fee = parsed
    return _format_eur(gross - fee)


def apply_capture_settlement(pledge: dict, payload: dict) -> dict:
    """Store capture settlement on the pledge and set ``received_net_eur`` when known."""
    capture = capture_resource_from_payload(payload)
    pledge_ccy = str(pledge.get("currency") or "EUR").strip().upper()
    settlement = parse_seller_receivable_breakdown(capture or {}) if capture else None
    if settlement:
        pledge["capture_settlement"] = settlement
        net = settlement.get("net_amount")
        parsed = None
        if isinstance(net, dict) and str(net.get("currency") or "").upper() == "EUR":
            parsed = _decimal_text(str(net.get("value") or ""))
        if parsed is not None:
            pledge["received_net_eur"] = _format_eur(parsed)
            pledge["capture_received_net_eur"] = pledge["received_net_eur"]
            return pledge
        net_ccy = str(net.get("currency") or "unknown").upper() if isinstance(net, dict) else "unknown"
        logger.warning(
            "PayPal capture net_amount is not EUR for pledge %s (net_currency=%s)",
            pledge.get("_id"),
            net_ccy,
        )
        pledge.pop("received_net_eur", None)
        pledge.pop("capture_received_net_eur", None)
        return pledge
    if pledge_ccy == "EUR":
        legacy = _eur_capture_without_breakdown(pledge, capture)
        if legacy is not None:
            pledge["received_net_eur"] = legacy
            pledge["capture_received_net_eur"] = legacy
        return pledge
    logger.warning(
        "PayPal capture missing seller_receivable_breakdown for pledge %s (%s)",
        pledge.get("_id"),
        pledge_ccy,
    )
    pledge.setdefault("capture_settlement", None)
    return pledge


def capture_net_eur_baseline(pledge: dict) -> Optional[Decimal]:
    """Immutable EUR net at capture (before any refund)."""
    frozen = pledge.get("capture_received_net_eur")
    if frozen is not None and str(frozen).strip():
        return _decimal_text(str(frozen))
    settlement = pledge.get("capture_settlement")
    if isinstance(settlement, dict):
        net = settlement.get("net_amount")
        if isinstance(net, dict) and str(net.get("currency") or "").upper() == "EUR":
            return _decimal_text(str(net.get("value") or ""))
    pledge_ccy = str(pledge.get("currency") or "EUR").strip().upper()
    if pledge_ccy == "EUR":
        gross = _decimal_text(str(pledge.get("amount_eur") or "0"))
        if gross is not None:
            return gross
    return None


def _capture_exchange_rate_to_eur(pledge: dict) -> Optional[Decimal]:
    settlement = pledge.get("capture_settlement")
    if not isinstance(settlement, dict):
        return None
    rate = settlement.get("exchange_rate")
    if not isinstance(rate, dict):
        return None
    if str(rate.get("target_currency") or "").upper() != "EUR":
        return None
    return _decimal_text(str(rate.get("value") or ""))


def estimate_refund_net_eur_conservative(pledge: dict, refund_row: dict) -> Optional[Decimal]:
    """When PayPal omits payable breakdown: deduct at least capture-rate × refund native (never raises net)."""
    pledge_ccy = str(pledge.get("currency") or "EUR").strip().upper()
    if pledge_ccy == "EUR":
        return _decimal_text(str(refund_row.get("amount") or "0"))
    refund_native = _decimal_text(str(refund_row.get("amount") or "0"))
    if refund_native is None or refund_native <= Decimal("0"):
        return None
    rate = _capture_exchange_rate_to_eur(pledge)
    if rate is None or rate <= Decimal("0"):
        return None
    return (refund_native * rate).quantize(Decimal("0.01"))


def enrich_refund_row_settlement(
    pledge: dict,
    refund_payload: Optional[dict],
    refund_row: dict,
) -> dict:
    """Attach ``refund_net_eur`` on one refund row without mutating the pledge."""
    payload = refund_payload if isinstance(refund_payload, dict) else {}
    payable = parse_seller_payable_breakdown(payload)
    if payable:
        return {**refund_row, "refund_net_eur": payable["value"]}
    pledge_ccy = str(pledge.get("currency") or "EUR").strip().upper()
    if pledge_ccy == "EUR":
        amount = _decimal_text(str(refund_row.get("amount") or "0"))
        if amount is not None:
            return {**refund_row, "refund_net_eur": _format_eur(amount)}
    estimated = estimate_refund_net_eur_conservative(pledge, refund_row)
    if estimated is not None:
        return {**refund_row, "refund_net_eur": _format_eur(estimated)}
    logger.warning(
        "PayPal refund missing seller_payable_breakdown for pledge %s (%s)",
        pledge.get("_id"),
        pledge_ccy,
    )
    return refund_row


def _deduped_refund_rows(refunds: list[dict]) -> list[dict]:
    seen: set[str] = set()
    rows: list[dict] = []
    for row in refunds:
        if not isinstance(row, dict):
            continue
        refund_id = str(row.get("id") or "").strip()
        if not refund_id or refund_id in seen:
            continue
        status = str(row.get("status") or "COMPLETED").upper()
        if status not in {"COMPLETED", "PENDING", "REFUNDED"}:
            continue
        seen.add(refund_id)
        rows.append(row)
    return rows


def recompute_received_net_eur(pledge: dict, refunds: Optional[list[dict]] = None) -> None:
    """``received_net_eur`` = capture EUR net minus unique refund EUR reversals (idempotent)."""
    base = capture_net_eur_baseline(pledge)
    if base is None:
        return
    rows = _deduped_refund_rows(refunds if refunds is not None else _pledge_refund_list(pledge))
    total_reversal = Decimal("0.00")
    for row in rows:
        text = row.get("refund_net_eur")
        if text is not None and str(text).strip():
            parsed = _decimal_text(str(text))
            if parsed is not None:
                total_reversal += parsed
                continue
        pledge_ccy = str(pledge.get("currency") or "EUR").strip().upper()
        if pledge_ccy == "EUR":
            parsed = _decimal_text(str(row.get("amount") or "0"))
            if parsed is not None:
                total_reversal += parsed
    remaining = max(Decimal("0.00"), base - total_reversal)
    pledge["received_net_eur"] = _format_eur(remaining)


def _pledge_refund_list(pledge: dict) -> list[dict]:
    raw = pledge.get("refunds")
    return list(raw) if isinstance(raw, list) else []


def apply_refund_settlement(pledge: dict, refund_payload: dict, refund_row: dict) -> tuple[dict, dict]:
    """Legacy helper: enrich row then recompute (use from ``reconcile_refund_on_pledge``)."""
    row = enrich_refund_row_settlement(pledge, refund_payload, refund_row)
    refunds = _append_refund_row_compat(_pledge_refund_list(pledge), row)
    pledge["refunds"] = refunds
    recompute_received_net_eur(pledge, refunds)
    return pledge, row


def _append_refund_row_compat(refunds: list[dict], row: dict) -> list[dict]:
    refund_id = str(row.get("id") or "").strip()
    if not refund_id:
        return refunds
    if any(str(existing.get("id") or "") == refund_id for existing in refunds):
        return refunds
    return [*refunds, row]


def settlement_finance_fields(pledge: dict) -> dict[str, Any]:
    """Fields to copy onto ``pledge_captured`` finance rows."""
    out: dict[str, Any] = {}
    if pledge.get("capture_settlement") is not None:
        out["capture_settlement"] = pledge.get("capture_settlement")
    if pledge.get("received_net_eur") is not None:
        out["received_net_eur"] = pledge.get("received_net_eur")
    return out


def _ledger_euros(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0").replace(",", "."))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def finance_entry_received_net_eur(entry: dict) -> Decimal:
    """EUR received on a ``pledge_captured`` finance line."""
    if str(entry.get("kind") or "") != "pledge_captured":
        return Decimal("0.00")
    text = entry.get("received_net_eur")
    if text is not None and str(text).strip():
        parsed = _decimal_text(str(text))
        if parsed is not None:
            return parsed
    ccy = str(entry.get("currency") or "EUR").strip().upper()
    if ccy == "EUR":
        return _ledger_euros(entry.get("amount_eur"))
    return Decimal("0.00")


def finance_entry_refund_net_eur(entry: dict) -> Decimal:
    """EUR taken back on a ``pledge_refunded`` finance line."""
    if str(entry.get("kind") or "") != "pledge_refunded":
        return Decimal("0.00")
    text = entry.get("refund_net_eur")
    if text is not None and str(text).strip():
        parsed = _decimal_text(str(text))
        if parsed is not None:
            return parsed
    ccy = str(entry.get("currency") or "EUR").strip().upper()
    if ccy == "EUR":
        return _ledger_euros(entry.get("amount_eur"))
    return Decimal("0.00")


def pledge_spendable_net_eur(pledge: dict) -> Decimal:
    """EUR balance for project payouts: capture net after PayPal fees/FX, minus refund EUR takebacks."""
    received = pledge.get("received_net_eur")
    if received is not None and str(received).strip():
        parsed = _decimal_text(str(received))
        if parsed is not None:
            return parsed
    pledge_ccy = str(pledge.get("currency") or "EUR").strip().upper()
    if pledge_ccy != "EUR":
        return Decimal("0.00")
    from .pledges import refunded_amount_from_pledge

    gross = _decimal_text(str(pledge.get("amount_eur") or "0")) or Decimal("0.00")
    return gross - refunded_amount_from_pledge(pledge)
