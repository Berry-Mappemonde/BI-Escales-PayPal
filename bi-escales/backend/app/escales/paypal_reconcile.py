"""Read-only reconciliation: escales finance journal vs PayPal Transaction Search.

Transaction Search API:
https://developer.paypal.com/docs/api/transaction-search/v1/#transactions_search
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Optional

from .paypal_txn_search import clamp_transaction_search_range

SANDBOX_REPORTING_LAG_HOURS = 3
RECONCILE_NOTE = (
    "Matching uses PayPal capture_id = transaction_id (not calendar dates alone). "
    "Sandbox Transaction Search often lags the finance journal by about 3 hours."
)


def _ledger_captures(entries: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for entry in entries:
        kind = str(entry.get("kind") or "")
        if kind not in {"pledge_captured", "pledge_capture_pending"}:
            continue
        capture_id = str(entry.get("capture_id") or "").strip()
        if not capture_id:
            continue
        rows.append({
            "finance_id": entry.get("_id"),
            "pledge_id": entry.get("pledge_id"),
            "capture_id": capture_id,
            "amount_eur": entry.get("amount_eur"),
            "at": entry.get("at"),
        })
    return rows


def _paypal_rows(payload: dict) -> list[dict]:
    details = payload.get("transaction_details") or []
    rows: list[dict] = []
    for item in details:
        if not isinstance(item, dict):
            continue
        info = item.get("transaction_info") or {}
        txn_id = str(info.get("transaction_id") or "").strip()
        if not txn_id:
            continue
        amount = (info.get("transaction_amount") or {}).get("value")
        rows.append({
            "transaction_id": txn_id,
            "amount": amount,
            "custom_field": info.get("custom_field"),
            "invoice_id": info.get("invoice_id"),
            "transaction_status": info.get("transaction_status"),
        })
    return rows


def _parse_moment(raw: Optional[str]) -> Optional[dt.datetime]:
    text = (raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.astimezone(dt.timezone.utc)


def _search_window_from_ledger(
    ledger: list[dict],
    start_date: str,
    end_date: str,
) -> tuple[str, str]:
    """Widen the PayPal search window to cover ledger capture timestamps (+ lag)."""
    moments: list[dt.datetime] = []
    for row in ledger:
        moment = _parse_moment(str(row.get("at") or ""))
        if moment:
            moments.append(moment)
    if not moments:
        return clamp_transaction_search_range(start_date, end_date)
    lag = dt.timedelta(hours=SANDBOX_REPORTING_LAG_HOURS)
    start = min(moments) - dt.timedelta(days=1)
    end = max(moments) + lag
    return clamp_transaction_search_range(start.isoformat(), end.isoformat())


async def reconcile_paypal_ledger(
    *,
    start_date: str,
    end_date: str,
    client: Any,
    finance_entries: list[dict],
) -> dict:
    """Compare captured pledges in ``escales_finance`` to PayPal reporting (read-only)."""
    ledger = _ledger_captures(finance_entries)
    search_start, search_end = _search_window_from_ledger(ledger, start_date, end_date)
    paypal_payload = client.search_transactions(start_date=search_start, end_date=search_end)
    paypal = _paypal_rows(paypal_payload if isinstance(paypal_payload, dict) else {})

    ledger_by_id = {row["capture_id"]: row for row in ledger if row.get("capture_id")}
    paypal_by_id = {row["transaction_id"]: row for row in paypal if row.get("transaction_id")}

    matched: list[dict] = []
    for capture_id, left in ledger_by_id.items():
        right = paypal_by_id.get(capture_id)
        if right is None:
            continue
        amount_left = Decimal(str(left.get("amount_eur") or "0"))
        amount_right = Decimal(str(right.get("amount") or "0"))
        matched.append({
            "capture_id": capture_id,
            "pledge_id": left.get("pledge_id"),
            "ledger_amount_eur": str(amount_left),
            "paypal_amount": str(amount_right),
            "amounts_match": amount_left == amount_right,
        })

    ledger_only = [
        row for capture_id, row in ledger_by_id.items() if capture_id not in paypal_by_id
    ]
    paypal_only = [
        row for txn_id, row in paypal_by_id.items() if txn_id not in ledger_by_id
    ]

    return {
        "start_date": search_start,
        "end_date": search_end,
        "searched_start_date": search_start,
        "searched_end_date": search_end,
        "requested_start_date": start_date,
        "requested_end_date": end_date,
        "match_key": "capture_id",
        "sandbox_reporting_lag_hours": SANDBOX_REPORTING_LAG_HOURS,
        "note": RECONCILE_NOTE,
        "ledger_capture_count": len(ledger),
        "paypal_transaction_count": len(paypal),
        "matched": matched,
        "ledger_only": ledger_only,
        "paypal_only": paypal_only,
        "balanced": not ledger_only and not paypal_only,
    }
