"""Read-only PayPal sandbox smoke for the Server SDK gateway.

Prints resource ids and statuses. Does not print tokens, secrets, emails, or
amounts. Exits without a network call when sandbox credentials are absent.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))


def _id_status(kind: str, payload: dict) -> None:
    resource_id = payload.get("id") or ""
    status = payload.get("status") or ""
    print(f"{kind} id={resource_id} status={status}")


def _run_reads() -> int:
    from app.escales.config import load_config
    from app.escales.paypal_client import PayPalClient, PayPalError
    from app.escales.paypal_txn_search import default_transaction_search_window

    os.environ["ESCALES_PAYPAL_SDK_ENABLED"] = "1"
    client = PayPalClient(load_config())
    print("paypal_sdk_smoke sandbox")

    start_date, end_date = default_transaction_search_window()
    try:
        page = client.search_transactions(start_date=start_date, end_date=end_date)
    except PayPalError as exc:
        print(f"paypal_error status={exc.status}")
        return 1
    details = page.get("transaction_details") or []
    print(f"transactions count={len(details) if isinstance(details, list) else 0}")
    if isinstance(details, list):
        for row in details:
            info = row.get("transaction_info") if isinstance(row, dict) else None
            info = info if isinstance(info, dict) else {}
            txn_id = info.get("transaction_id") or ""
            status = info.get("transaction_status") or ""
            print(f"transaction id={txn_id} status={status}")

    optional = (
        ("order", "PAYPAL_SDK_SMOKE_ORDER_ID", "get_order"),
        ("authorization", "PAYPAL_SDK_SMOKE_AUTHORIZATION_ID", "get_authorization"),
        ("setup_token", "PAYPAL_SDK_SMOKE_SETUP_TOKEN_ID", "get_setup_token"),
        ("plan", "PAYPAL_SDK_SMOKE_PLAN_ID", "get_billing_plan"),
        ("subscription", "PAYPAL_SDK_SMOKE_SUBSCRIPTION_ID", "get_subscription"),
    )
    for kind, env_name, method in optional:
        resource_id = (os.environ.get(env_name) or "").strip()
        if not resource_id:
            continue
        try:
            payload = getattr(client, method)(resource_id)
        except PayPalError as exc:
            print(f"paypal_error status={exc.status}")
            return 1
        if isinstance(payload, dict):
            _id_status(kind, payload)

    product_id = (os.environ.get("PAYPAL_SDK_SMOKE_PRODUCT_ID") or "").strip()
    if product_id:
        try:
            plans = client.list_billing_plans(product_id=product_id)
        except PayPalError as exc:
            print(f"paypal_error status={exc.status}")
            return 1
        rows = plans.get("plans") if isinstance(plans, dict) else None
        rows = rows if isinstance(rows, list) else []
        print(f"plans count={len(rows)}")
        for row in rows:
            if isinstance(row, dict):
                _id_status("plan", row)
    return 0


def main() -> int:
    env = (os.environ.get("PAYPAL_ENV") or "").strip().lower()
    if env != "sandbox":
        print("refused: PAYPAL_ENV must be sandbox; no PayPal call was made")
        return 2
    client_id = (os.environ.get("PAYPAL_CLIENT_ID") or "").strip()
    client_secret = (os.environ.get("PAYPAL_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        print("skipped: sandbox credentials are not set; no PayPal call was made")
        return 0
    try:
        return _run_reads()
    except Exception as exc:
        print(f"transport_error type={type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
