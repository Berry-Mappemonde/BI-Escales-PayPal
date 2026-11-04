"""Billing subscriptions — idempotent 'Crew supporter' catalog setup (admin)."""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any, Optional

from .ledger import list_finance_entries, now_iso, record_finance, update_finance_entry
from .paypal_idempotency import paypal_request_id
from .pledges import _client_key

CREW_PRODUCT_NAME = "Crew supporter"
CREW_PLAN_NAME = "Crew supporter monthly"
CREW_SETUP_KEY = "crew_supporter_catalog"
SUBSCRIPTION_CREATE_CACHE_KIND = "paypal_subscription_create_cache"
SUBSCRIPTION_CREATE_CACHE_MAX = 32


async def _catalog_row() -> Optional[dict]:
    for entry in await list_finance_entries():
        if entry.get("kind") != "subscription_catalog_ready":
            continue
        if entry.get("setup_key") == CREW_SETUP_KEY:
            return entry
    return None


def _catalog_product_id(products_payload: dict) -> Optional[str]:
    for item in products_payload.get("products") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").strip() == CREW_PRODUCT_NAME:
            product_id = str(item.get("id") or "").strip()
            if product_id:
                return product_id
    return None


def _catalog_plan_id(plans_payload: dict) -> Optional[str]:
    for item in plans_payload.get("plans") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").strip() == CREW_PLAN_NAME:
            plan_id = str(item.get("id") or "").strip()
            if plan_id:
                return plan_id
    return None


async def _hydrate_catalog_from_paypal(client: Any) -> Optional[dict]:
    """Find existing Crew supporter product/plan on PayPal and remember locally."""
    product_id: Optional[str] = None
    iterator = getattr(client, "iter_billing_product_pages", None)
    if callable(iterator):
        for page_payload in iterator():
            product_id = _catalog_product_id(page_payload)
            if product_id:
                break
    else:
        product_id = _catalog_product_id(client.list_billing_products())
    if not product_id:
        return None
    plans = client.list_billing_plans(product_id=product_id)
    plan_id = _catalog_plan_id(plans)
    if not plan_id:
        return None
    await record_finance(
        "subscription_catalog_ready",
        setup_key=CREW_SETUP_KEY,
        product_id=product_id,
        plan_id=plan_id,
        catalog_source="paypal_list",
    )
    return {"product_id": product_id, "plan_id": plan_id}


async def ensure_crew_supporter_catalog(client: Any) -> dict:
    """Create product + monthly EUR plan once (idempotent)."""
    existing = await _catalog_row()
    if existing:
        return {
            "product_id": existing.get("product_id"),
            "plan_id": existing.get("plan_id"),
            "idempotent": True,
        }
    hydrated = await _hydrate_catalog_from_paypal(client)
    if hydrated:
        return {
            "product_id": hydrated.get("product_id"),
            "plan_id": hydrated.get("plan_id"),
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


async def resolve_crew_supporter_plan_id(client: Any) -> Optional[str]:
    """Local memory or PayPal catalog lookup only — never creates product/plan."""
    row = await _catalog_row()
    if row:
        plan_id = str(row.get("plan_id") or "").strip()
        if plan_id:
            return plan_id
    hydrated = await _hydrate_catalog_from_paypal(client)
    if not hydrated:
        return None
    plan_id = str(hydrated.get("plan_id") or "").strip()
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


def _subscription_create_body_hash(*, return_url: str, cancel_url: str) -> str:
    payload = json.dumps(
        {"return_url": return_url, "cancel_url": cancel_url},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


async def _subscription_create_cache_get(client_key: str, body_hash: str) -> Optional[dict]:
    for entry in await list_finance_entries():
        if entry.get("kind") != SUBSCRIPTION_CREATE_CACHE_KIND:
            continue
        if str(entry.get("client_key") or "") != client_key:
            continue
        if str(entry.get("body_hash") or "") != body_hash:
            continue
        cached = entry.get("create_response")
        if isinstance(cached, dict):
            return dict(cached)
    return None


async def _subscription_create_cache_put(
    client_key: str,
    body_hash: str,
    response: dict,
) -> None:
    entries = await list_finance_entries()
    cache_rows = [row for row in entries if row.get("kind") == SUBSCRIPTION_CREATE_CACHE_KIND]
    for entry in cache_rows:
        if (
            str(entry.get("client_key") or "") == client_key
            and str(entry.get("body_hash") or "") == body_hash
        ):
            await update_finance_entry(
                str(entry.get("_id") or ""),
                {"create_response": response, "at": now_iso()},
            )
            return
    patch = {
        "client_key": client_key,
        "body_hash": body_hash,
        "create_response": response,
        "at": now_iso(),
    }
    if len(cache_rows) >= SUBSCRIPTION_CREATE_CACHE_MAX:
        oldest = min(cache_rows, key=lambda row: str(row.get("at") or ""))
        await update_finance_entry(str(oldest.get("_id") or ""), patch)
        return
    await record_finance(SUBSCRIPTION_CREATE_CACHE_KIND, **patch)


def _subscription_create_response(
    catalog: dict,
    plan_id: str,
    payload: dict,
) -> dict:
    subscription_id = str(payload.get("id") or "")
    return {
        "product_id": catalog.get("product_id"),
        "plan_id": plan_id,
        "subscription_id": subscription_id,
        "approve_link": _subscription_approve_link(payload),
        "status": payload.get("status"),
    }


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
    replay_key = _client_key(client_key)
    body_hash = _subscription_create_body_hash(return_url=return_url, cancel_url=cancel_url)
    if replay_key:
        cached = await _subscription_create_cache_get(replay_key, body_hash)
        if cached:
            return cached
    idempotency = replay_key[:127] if replay_key else secrets.token_hex(16)
    payload = client.create_billing_subscription(
        plan_id=plan_id,
        return_url=return_url,
        cancel_url=cancel_url,
        idempotency_key=idempotency,
    )
    result = _subscription_create_response(catalog, plan_id, payload)
    if replay_key:
        await _subscription_create_cache_put(replay_key, body_hash, result)
    return result


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
    expected_plan = await resolve_crew_supporter_plan_id(client)
    if not expected_plan:
        raise ValueError("crew supporter plan is not configured")
    remote_plan = str(remote.get("plan_id") or plan_id or "").strip()
    if remote_plan != expected_plan:
        raise ValueError("subscription plan_id does not match the Crew supporter plan")
    status = str(remote.get("status") or "").strip().upper()
    if status != "ACTIVE":
        raise ValueError(
            f"subscription status is {status or 'unknown'}; complete PayPal approval before recording"
        )
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
