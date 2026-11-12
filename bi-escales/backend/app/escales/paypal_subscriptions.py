"""Billing subscriptions — idempotent bilingual Crew membership catalog setup (admin).

Crew membership is the association membership (adhésion): 10 EUR per year.
The first catalog, 5 EUR per month, is kept: nothing here deletes or changes it,
and a subscription on one of its plans still verifies as a Crew subscription.
"""

from __future__ import annotations

import asyncio
import weakref
from decimal import Decimal, InvalidOperation
import hashlib
import json
import secrets
from typing import Any, Optional

from .app_i18n import normalize_app_lang
from .ledger import list_finance_entries, now_iso, record_finance, update_finance_entry
from .paypal_client import paypal_checkout_locale
from .paypal_idempotency import paypal_request_id
from .pledges import _client_key

# Catalog v2: the plans the app shows and sells. A new key, so that the finance row
# and the PayPal request ids are new and the v1 catalog is neither reused nor touched.
CREW_SETUP_KEY = "crew_membership_catalog_v2"
CREW_PLAN_AMOUNT_EUR = "10.00"
CREW_PLAN_INTERVAL_UNIT = "YEAR"

# Catalog v1: 5 EUR per month. Read-only here. Its plan ids are still accepted when a
# subscription is verified, so existing sandbox subscribers keep working.
CREW_LEGACY_SETUP_KEY = "crew_supporter_catalog"

SUBSCRIPTION_CREATE_CACHE_KIND = "paypal_subscription_create_cache"
SUBSCRIPTION_CREATE_CACHE_MAX = 32

CREW_CATALOG_LANGS = ("en", "fr")

# A v1 English plan id that was hard-coded before the catalog row existed. Legacy only:
# accepted on verification, never offered for a new subscription.
CREW_PLAN_ID_EN_FALLBACK = "P-4PS00218TX624722ENLVZY3I"

CREW_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "product_name": "Crew membership",
        "product_description": (
            "Association membership (adhésion) of Berry-Mappemonde for Blue Intelligence Escales: "
            "10 EUR per year"
        ),
        "plan_name": "Crew membership (10 EUR per year)",
    },
    "fr": {
        "product_name": "Adhésion Crew",
        "product_description": (
            "Adhésion à l'association Berry-Mappemonde pour Blue Intelligence Escales : 10 EUR par an"
        ),
        "plan_name": "Adhésion Crew (10 EUR par an)",
    },
}

# The v1 names, kept for reference and tests. No product or plan is created with them any more.
CREW_LEGACY_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "product_name": "Crew supporter",
        "product_description": "Monthly crew supporter subscription for Blue Intelligence Escales",
        "plan_name": "Crew supporter (monthly)",
    },
    "fr": {
        "product_name": "Soutien d'équipage",
        "product_description": "Abonnement mensuel de soutien d'équipage pour Blue Intelligence Escales",
        "plan_name": "Soutien d'équipage (mensuel)",
    },
}


async def _catalog_row(setup_key: str = CREW_SETUP_KEY) -> Optional[dict]:
    """The stored catalog for ``setup_key``: the current one (v2) unless the legacy key is asked for."""
    for entry in await list_finance_entries():
        if entry.get("kind") != "subscription_catalog_ready":
            continue
        if entry.get("setup_key") == setup_key:
            return entry
    return None


async def legacy_crew_plan_ids() -> set[str]:
    """Plan ids of the v1 catalog (5 EUR per month), from local records only.

    Used to keep verifying subscriptions made before the 10 EUR per year plans.
    No PayPal call: the v1 catalog is never looked up, changed or recreated.
    """
    ids = {CREW_PLAN_ID_EN_FALLBACK}
    for entry in await list_finance_entries():
        if entry.get("kind") != "subscription_catalog_ready":
            continue
        if entry.get("setup_key") != CREW_LEGACY_SETUP_KEY:
            continue
        for key in ("plan_id", *(f"plan_id_{lang}" for lang in CREW_CATALOG_LANGS)):
            plan_id = str(entry.get(key) or "").strip()
            if plan_id:
                ids.add(plan_id)
    return ids


def _catalog_product_id(products_payload: dict, product_name: str) -> Optional[str]:
    target = (product_name or "").strip()
    for item in products_payload.get("products") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").strip() == target:
            product_id = str(item.get("id") or "").strip()
            if product_id:
                return product_id
    return None


def _catalog_plan_id(plans_payload: dict, plan_name: str) -> Optional[str]:
    target = (plan_name or "").strip()
    for item in plans_payload.get("plans") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").strip() == target:
            plan_id = str(item.get("id") or "").strip()
            if plan_id:
                return plan_id
    return None


def _row_plan_id(row: dict, lang: str) -> Optional[str]:
    key = f"plan_id_{lang}"
    plan_id = str(row.get(key) or "").strip()
    if plan_id:
        return plan_id
    if lang == "en":
        legacy = str(row.get("plan_id") or "").strip()
        if legacy:
            return legacy
    return None


def _row_product_id(row: dict, lang: str) -> Optional[str]:
    key = f"product_id_{lang}"
    product_id = str(row.get(key) or "").strip()
    if product_id:
        return product_id
    if lang == "en":
        legacy = str(row.get("product_id") or "").strip()
        if legacy:
            return legacy
    return None


async def _list_products(client: Any) -> list[dict]:
    pages: list[dict] = []
    iterator = getattr(client, "iter_billing_product_pages", None)
    if callable(iterator):
        for page_payload in iterator():
            pages.append(page_payload)
    else:
        pages.append(client.list_billing_products())
    return pages


async def _hydrate_lang_from_paypal(client: Any, lang: str) -> Optional[dict[str, str]]:
    labels = CREW_LABELS[lang]
    product_id: Optional[str] = None
    for page_payload in await _list_products(client):
        product_id = _catalog_product_id(page_payload, labels["product_name"])
        if product_id:
            break
    if not product_id:
        return None
    plans = client.list_billing_plans(product_id=product_id)
    plan_id = _catalog_plan_id(plans, labels["plan_name"])
    if not plan_id:
        return None
    return {"product_id": product_id, "plan_id": plan_id}


async def _hydrate_catalog_from_paypal(client: Any) -> Optional[dict]:
    """Find existing Crew supporter product/plan on PayPal and remember locally."""
    patch: dict[str, str] = {}
    for lang in CREW_CATALOG_LANGS:
        hydrated = await _hydrate_lang_from_paypal(client, lang)
        if not hydrated:
            continue
        patch[f"product_id_{lang}"] = hydrated["product_id"]
        patch[f"plan_id_{lang}"] = hydrated["plan_id"]
    if not patch:
        return None
    await record_finance(
        "subscription_catalog_ready",
        setup_key=CREW_SETUP_KEY,
        catalog_source="paypal_list",
        **patch,
    )
    return patch


async def _ensure_lang_catalog(client: Any, lang: str) -> dict[str, str]:
    labels = CREW_LABELS[lang]
    row = await _catalog_row()
    product_id = _row_product_id(row or {}, lang) if row else None
    plan_id = _row_plan_id(row or {}, lang) if row else None
    if product_id and plan_id:
        return {"product_id": product_id, "plan_id": plan_id}
    hydrated = await _hydrate_lang_from_paypal(client, lang)
    if hydrated:
        patch = {
            f"product_id_{lang}": hydrated["product_id"],
            f"plan_id_{lang}": hydrated["plan_id"],
        }
        if row:
            await update_finance_entry(str(row.get("_id") or ""), patch)
        else:
            await record_finance(
                "subscription_catalog_ready",
                setup_key=CREW_SETUP_KEY,
                **patch,
            )
        return hydrated
    product = client.create_billing_product(
        name=labels["product_name"],
        description=labels["product_description"],
        idempotency_key=paypal_request_id(CREW_SETUP_KEY, f"product-{lang}"),
    )
    product_id = str(product.get("id") or "")
    plan = client.create_billing_plan(
        product_id=product_id,
        name=labels["plan_name"],
        amount_eur=CREW_PLAN_AMOUNT_EUR,
        interval_unit=CREW_PLAN_INTERVAL_UNIT,
        idempotency_key=paypal_request_id(CREW_SETUP_KEY, f"plan-{lang}"),
    )
    plan_id = str(plan.get("id") or "")
    patch = {f"product_id_{lang}": product_id, f"plan_id_{lang}": plan_id}
    if row:
        await update_finance_entry(str(row.get("_id") or ""), patch)
    else:
        await record_finance(
            "subscription_catalog_ready",
            setup_key=CREW_SETUP_KEY,
            **patch,
        )
    return {"product_id": product_id, "plan_id": plan_id}


async def ensure_crew_supporter_catalog(client: Any) -> dict:
    """Create the bilingual product and the 10 EUR per year plans once (idempotent).

    Works on catalog v2 only. A v1 catalog on the host is left exactly as it is.
    """
    row = await _catalog_row()
    if row and all(_row_plan_id(row, lang) for lang in CREW_CATALOG_LANGS):
        return {
            "product_id_en": _row_product_id(row, "en"),
            "plan_id_en": _row_plan_id(row, "en"),
            "product_id_fr": _row_product_id(row, "fr"),
            "plan_id_fr": _row_plan_id(row, "fr"),
            "idempotent": True,
        }
    hydrated = await _hydrate_catalog_from_paypal(client)
    if hydrated and all(f"plan_id_{lang}" in hydrated for lang in CREW_CATALOG_LANGS):
        return {**hydrated, "idempotent": True}
    created: dict[str, str] = {}
    idempotent = True
    for lang in CREW_CATALOG_LANGS:
        before = await _catalog_row()
        had = _row_plan_id(before or {}, lang) if before else None
        piece = await _ensure_lang_catalog(client, lang)
        if not had:
            idempotent = False
        created[f"product_id_{lang}"] = piece["product_id"]
        created[f"plan_id_{lang}"] = piece["plan_id"]
    return {**created, "idempotent": idempotent}


async def public_crew_supporter_plan_id(lang: Optional[str] = None) -> Optional[str]:
    row = await _catalog_row()
    if not row:
        return None
    app_lang = normalize_app_lang(lang)
    plan_id = _row_plan_id(row, app_lang)
    return plan_id or None


async def resolve_crew_supporter_plan_id(client: Any, lang: Optional[str] = None) -> Optional[str]:
    """Local memory or PayPal catalog lookup only — never creates product/plan.

    Returns the 10 EUR per year plan, or ``None`` until that catalog exists on the
    host. It never falls back to a v1 plan: the app must not sell 5 EUR per month
    under a "10 EUR per year" label.
    """
    app_lang = normalize_app_lang(lang)
    row = await _catalog_row()
    if row:
        plan_id = _row_plan_id(row, app_lang)
        if plan_id:
            return plan_id
    hydrated = await _hydrate_lang_from_paypal(client, app_lang)
    if not hydrated:
        return None
    patch = {
        f"product_id_{app_lang}": hydrated["product_id"],
        f"plan_id_{app_lang}": hydrated["plan_id"],
    }
    if row:
        await update_finance_entry(str(row.get("_id") or ""), patch)
    else:
        await record_finance("subscription_catalog_ready", setup_key=CREW_SETUP_KEY, **patch)
    return hydrated.get("plan_id")


async def crew_supporter_plan_ids(client: Any) -> set[str]:
    """Every plan id that counts as a Crew subscription: the current plans and the v1 ones."""
    await ensure_crew_supporter_catalog(client)
    row = await _catalog_row()
    ids: set[str] = set()
    for lang in CREW_CATALOG_LANGS:
        plan_id = _row_plan_id(row or {}, lang) if row else None
        if plan_id:
            ids.add(plan_id)
    if not ids:
        # No current catalog: nothing is configured, and legacy ids alone do not make it so.
        return ids
    return ids | await legacy_crew_plan_ids()


def _subscription_approve_link(payload: dict) -> Optional[str]:
    for link in payload.get("links") or []:
        if not isinstance(link, dict):
            continue
        if str(link.get("rel") or "").lower() == "approve":
            href = str(link.get("href") or "").strip()
            if href:
                return href
    return None


def _subscription_create_body_hash(*, return_url: str, cancel_url: str, lang: str) -> str:
    payload = json.dumps(
        {"return_url": return_url, "cancel_url": cancel_url, "lang": lang},
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
    *,
    lang: str,
) -> dict:
    subscription_id = str(payload.get("id") or "")
    return {
        "product_id": catalog.get(f"product_id_{lang}") or catalog.get("product_id"),
        "plan_id": plan_id,
        "subscription_id": subscription_id,
        "approve_link": _subscription_approve_link(payload),
        "status": payload.get("status"),
        "lang": lang,
    }


_subscription_locks: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


async def create_crew_subscription(client: Any, **kwargs: Any) -> dict:
    loop = asyncio.get_running_loop()
    lock = _subscription_locks.setdefault(loop, asyncio.Lock())
    async with lock:
        return await _create_crew_subscription(client, **kwargs)


async def _create_crew_subscription(
    client: Any,
    *,
    return_url: str,
    cancel_url: str,
    client_key: Optional[str] = None,
    lang: Optional[str] = None,
    expected_plan_id: Optional[str] = None,
) -> dict:
    """Public buyer checkout: ensure catalog + create PayPal subscription."""
    app_lang = normalize_app_lang(lang)
    catalog = await ensure_crew_supporter_catalog(client)
    plan_id = str(catalog.get(f"plan_id_{app_lang}") or "")
    if not plan_id:
        plan_id = str(await resolve_crew_supporter_plan_id(client, lang=app_lang) or "")
    if not plan_id:
        raise ValueError("Crew membership plan is not configured")
    if expected_plan_id is not None:
        if expected_plan_id.strip() != plan_id:
            raise ValueError("subscription plan does not match the displayed selection")
        plan = client.get_billing_plan(plan_id)
        cycles = plan.get("billing_cycles") or []
        valid = plan.get("id") == plan_id and plan.get("status") == "ACTIVE" and len(cycles) == 1
        if valid:
            cycle = cycles[0]
            price = (cycle.get("pricing_scheme") or {}).get("fixed_price") or {}
            setup = (plan.get("payment_preferences") or {}).get("setup_fee") or {}
            try:
                valid = (cycle.get("tenure_type") == "REGULAR"
                    and cycle.get("frequency") == {"interval_unit": "YEAR", "interval_count": 1}
                    and price.get("currency_code") == "EUR"
                    and Decimal(str(price.get("value", "0"))) == Decimal("10.00")
                    and Decimal(str(setup.get("value", "0"))) == 0
                    and Decimal(str((plan.get("taxes") or {}).get("percentage", "0"))) == 0)
            except (InvalidOperation, TypeError, ValueError):
                valid = False
        if not valid:
            raise ValueError("subscription plan must be ACTIVE at 10 EUR per year without extras")
    replay_key = _client_key(client_key)
    body_hash = _subscription_create_body_hash(
        return_url=return_url,
        cancel_url=cancel_url,
        lang=app_lang,
    )
    if replay_key:
        cached = await _subscription_create_cache_get(replay_key, body_hash)
        if cached:
            if cached.get("plan_id") != plan_id:
                raise ValueError("subscription retry requires reconciliation after catalog change")
            return cached
    idempotency = replay_key[:127] if replay_key else secrets.token_hex(16)
    payload = client.create_billing_subscription(
        plan_id=plan_id,
        return_url=return_url,
        cancel_url=cancel_url,
        idempotency_key=idempotency,
        locale=paypal_checkout_locale(app_lang),
    )
    result = _subscription_create_response(catalog, plan_id, payload, lang=app_lang)
    if replay_key:
        await _subscription_create_cache_put(replay_key, body_hash, result)
    return result


async def subscription_known_locally(subscription_id: str) -> bool:
    """True when this subscription id came from our checkout cache or an existing local row."""
    sub_id = str(subscription_id or "").strip()
    if not sub_id:
        return False
    for entry in await list_finance_entries():
        kind = entry.get("kind")
        if kind == SUBSCRIPTION_CREATE_CACHE_KIND:
            cached = entry.get("create_response")
            if isinstance(cached, dict) and str(cached.get("subscription_id") or "") == sub_id:
                return True
        if kind == "paypal_subscription_local" and str(entry.get("subscription_id") or "") == sub_id:
            return True
    return False


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
    expected_plans = await crew_supporter_plan_ids(client)
    if not expected_plans:
        raise ValueError("Crew membership plan is not configured")
    remote_plan = str(remote.get("plan_id") or plan_id or "").strip()
    if remote_plan not in expected_plans:
        raise ValueError("subscription plan_id does not match the Crew membership plan")
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


# Backward-compatible English catalog names (tests and legacy rows).
CREW_PRODUCT_NAME = CREW_LABELS["en"]["product_name"]
CREW_PLAN_NAME = CREW_LABELS["en"]["plan_name"]
