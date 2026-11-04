"""Billing subscriptions — idempotent 'Crew supporter' catalog setup (admin)."""

from __future__ import annotations

import secrets
from typing import Any, Optional

from .ledger import list_finance_entries, now_iso, record_finance, update_finance_entry
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


async def public_crew_supporter_plan_id() -> Optional[str]:
    row = await _catalog_row()
    if not row:
        return None
    plan_id = str(row.get("plan_id") or "").strip()
    return plan_id or None


def _subscription_approve_link(payload: dict) -> Optional[str]:
    for link in payload.get("links") or []:
        if not isinstance(link, dict):
            continue
        if str(link.get("rel") or "").lower() == "approve":
            href = str(link.get("href") or "").strip()
            if href:
                return href
    return None


async def create_crew_subscription(
    client: Any,
    *,
    return_url: str,
    cancel_url: str,
    client_key: Optional[str] = None,
) -> dict:
    """Public buyer checkout: ensure catalog + create PayPal subscription."""
    catalog = await ensure_crew_supporter_catalog(client)
    plan_id = str(catalog.get("plan_id") or "")
    if not plan_id:
        raise ValueError("crew supporter plan is not configured")
    ref = str(client_key or "").strip() or secrets.token_hex(16)
    payload = client.create_billing_subscription(
        plan_id=plan_id,
        return_url=return_url,
        cancel_url=cancel_url,
        idempotency_key=paypal_request_id(ref, "sub-create"),
    )
    subscription_id = str(payload.get("id") or "")
    return {
        "product_id": catalog.get("product_id"),
        "plan_id": plan_id,
        "subscription_id": subscription_id,
        "approve_link": _subscription_approve_link(payload),
        "status": payload.get("status"),
    }


async def approve_crew_subscription(
    client: Any,
    *,
    subscription_id: str,
    plan_id: str,
) -> dict:
    """Record a buyer subscription after PayPal approval (verified read)."""
    sub_id = str(subscription_id or "").strip()
    if not sub_id:
        raise ValueError("subscription_id is required")
    remote = client.get_subscription(sub_id)
    remote_plan = str(remote.get("plan_id") or plan_id or "").strip()
    status = str(remote.get("status") or "ACTIVE")
    subscriber = remote.get("subscriber") if isinstance(remote.get("subscriber"), dict) else {}
    email = subscriber.get("email_address") if isinstance(subscriber, dict) else None
    return await record_subscription(
        subscription_id=sub_id,
        plan_id=remote_plan or plan_id,
        status=status,
        subscriber_email=str(email) if email else None,
    )


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
    patch: dict = {
        "plan_id": plan_id,
        "status": status,
        "updated_at": now_iso(),
    }
    if subscriber_email is not None:
        patch["subscriber_email"] = subscriber_email
    for entry in await list_finance_entries():
        if entry.get("kind") != "paypal_subscription_local":
            continue
        if str(entry.get("subscription_id") or "") != sub_id:
            continue
        if not str(plan_id or "").strip():
            patch["plan_id"] = entry.get("plan_id") or ""
        updated = await update_finance_entry(str(entry.get("_id") or ""), patch)
        if updated:
            return updated
    if not str(plan_id or "").strip():
        return {"skipped": True, "reason": "subscription row requires plan_id"}
    row = await record_finance(
        "paypal_subscription_local",
        subscription_id=sub_id,
        plan_id=plan_id,
        status=status,
        subscriber_email=subscriber_email,
    )
    return row


async def list_subscriptions_local() -> list[dict]:
    by_id: dict[str, dict] = {}
    for entry in await list_finance_entries():
        if entry.get("kind") != "paypal_subscription_local":
            continue
        sub_id = str(entry.get("subscription_id") or "")
        if not sub_id:
            continue
        row = {
            "subscription_id": sub_id,
            "plan_id": entry.get("plan_id"),
            "status": entry.get("status"),
            "subscriber_email": entry.get("subscriber_email"),
            "at": entry.get("at"),
            "updated_at": entry.get("updated_at"),
        }
        prev = by_id.get(sub_id)
        prev_stamp = str((prev or {}).get("updated_at") or (prev or {}).get("at") or "")
        stamp = str(row.get("updated_at") or row.get("at") or "")
        if prev is None or stamp >= prev_stamp:
            by_id[sub_id] = row
    return list(by_id.values())
