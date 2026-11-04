"""Billing subscriptions — idempotent 'Crew supporter' catalog setup (admin)."""

from __future__ import annotations

from typing import Any, Optional

from .ledger import list_finance_entries, record_finance
from .paypal_idempotency import paypal_request_id

CREW_PRODUCT_NAME = "Crew supporter"
CREW_PLAN_NAME = "Crew supporter monthly"
CREW_SETUP_KEY = "crew_supporter_catalog"


async def _catalog_row() -> Optional[dict]:
    for entry in await list_finance_entries():
        if entry.get("kind") != "subscription_catalog_ready":
            continue
        if entry.get("setup_key") == CREW_SETUP_KEY:
            return entry
    return None


async def ensure_crew_supporter_catalog(client: Any) -> dict:
    """Create product + monthly EUR plan once (idempotent)."""
    existing = await _catalog_row()
    if existing:
        return {
            "product_id": existing.get("product_id"),
            "plan_id": existing.get("plan_id"),
            "idempotent": True,
        }
    product = client.create_billing_product(
        name=CREW_PRODUCT_NAME,
        description="Monthly crew supporter subscription for Blue Intelligence Escales",
        idempotency_key=paypal_request_id(CREW_SETUP_KEY, "product"),
    )
    product_id = str(product.get("id") or "")
    plan = client.create_billing_plan(
        product_id=product_id,
        name=CREW_PLAN_NAME,
        amount_eur="5.00",
        interval_unit="MONTH",
        idempotency_key=paypal_request_id(CREW_SETUP_KEY, "plan"),
    )
    plan_id = str(plan.get("id") or "")
    await record_finance(
        "subscription_catalog_ready",
        setup_key=CREW_SETUP_KEY,
        product_id=product_id,
        plan_id=plan_id,
    )
    return {"product_id": product_id, "plan_id": plan_id, "idempotent": False}


async def record_subscription(
    *,
    subscription_id: str,
    plan_id: str,
    status: str,
    subscriber_email: Optional[str] = None,
) -> dict:
    sub_id = str(subscription_id or "").strip()
    if not sub_id:
        raise ValueError("subscription_id is required")
    row = await record_finance(
        "paypal_subscription_local",
        subscription_id=sub_id,
        plan_id=plan_id,
        status=status,
        subscriber_email=subscriber_email,
    )
    return row


async def list_subscriptions_local() -> list[dict]:
    rows: list[dict] = []
    for entry in await list_finance_entries():
        if entry.get("kind") != "paypal_subscription_local":
            continue
        rows.append({
            "subscription_id": entry.get("subscription_id"),
            "plan_id": entry.get("plan_id"),
            "status": entry.get("status"),
            "subscriber_email": entry.get("subscriber_email"),
            "at": entry.get("at"),
        })
    return rows
