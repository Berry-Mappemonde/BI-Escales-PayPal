"""Read-only reconciliation: escales finance journal vs PayPal Transaction Search.

Transaction Search API:
https://developer.paypal.com/docs/api/transaction-search/v1/#transactions_search
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional


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


def _match_key(row: dict) -> Optional[str]:
    for key in ("capture_id", "transaction_id"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return None


async def reconcile_paypal_ledger(
    *,
    start_date: str,
    end_date: str,
    client: Any,
    finance_entries: list[dict],
) -> dict:
    """Compare captured pledges in ``escales_finance`` to PayPal reporting (read-only)."""
    ledger = _ledger_captures(finance_entries)
    paypal_payload = client.search_transactions(start_date=start_date, end_date=end_date)
    paypal = _paypal_rows(paypal_payload if isinstance(paypal_payload, dict) else {})

    ledger_by_id = {_match_key(row): row for row in ledger if _match_key(row)}
    paypal_by_id = {_match_key(row): row for row in paypal if _match_key(row)}

    matched: list[dict] = []
    for key, left in ledger_by_id.items():
        right = paypal_by_id.get(key)
        if right is None:
            continue
        amount_left = Decimal(str(left.get("amount_eur") or "0"))
        amount_right = Decimal(str(right.get("amount") or "0"))
        matched.append({
            "capture_id": key,
            "pledge_id": left.get("pledge_id"),
            "ledger_amount_eur": str(amount_left),
            "paypal_amount": str(amount_right),
            "amounts_match": amount_left == amount_right,
        })

    ledger_only = [
        row for key, row in ledger_by_id.items() if key not in paypal_by_id
    ]
    paypal_only = [
        row for key, row in paypal_by_id.items() if key not in ledger_by_id
    ]

    return {
        "start_date": start_date,
        "end_date": end_date,
        "ledger_capture_count": len(ledger),
        "paypal_transaction_count": len(paypal),
        "matched": matched,
        "ledger_only": ledger_only,
        "paypal_only": paypal_only,
        "balanced": not ledger_only and not paypal_only,
    }
