"""Pledge state machine: created -> authorized -> captured | voided.

Nothing is captured or voided until a treasurer calls the matching route.
Forbidden transitions raise ``IllegalTransition`` (HTTP 409 at the edge).
Storage is ``escales_pledges`` when Mongo is configured, otherwise memory.
"""
from __future__ import annotations

import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from .config import AUTH_MAX_DAYS
from .ledger import (
    COLLECTIONS,
    get_ledger,
    now_iso,
    record_finance,
    reset_ledger,
)
from .paypal_client import PayPalError, approve_link, authorization_from

PLEDGES_COLLECTION = "escales_pledges"
MILESTONES_COLLECTION = "escales_milestones"
AUDIT_COLLECTION = "escales_audit"

_AMOUNT = re.compile(r"^\d+(?:\.\d{1,2})?$")


class IllegalTransition(Exception):
    def __init__(self, current: str, target: str):
        self.current = current
        self.target = target
        super().__init__(f"forbidden transition {current} -> {target}")


class PledgeNotFound(Exception):
    def __init__(self, pledge_id: str):
        self.pledge_id = pledge_id
        super().__init__(f"pledge {pledge_id} not found")


def default_expiration() -> str:
    import datetime as dt
    moment = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=AUTH_MAX_DAYS)
    return moment.replace(microsecond=0).isoformat()


def normalize_amount(raw: str) -> str:
    text = (raw or "").strip()
    if not _AMOUNT.match(text):
        raise ValueError("amount_eur must be a positive amount with at most 2 decimal places")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("amount_eur must be a positive amount with at most 2 decimal places") from exc
    if value <= 0:
        raise ValueError("amount_eur must be a positive amount with at most 2 decimal places")
    return f"{value:.2f}"


def to_public(doc: dict) -> dict:
    hidden = {"_id", "client_key"}
    out = {key: value for key, value in doc.items() if key not in hidden}
    out["id"] = doc["_id"]
    return out


def _require_text(value: str, field: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _client_key(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    key = raw.strip()
    if not key:
        return None
    if not 1 <= len(key) <= 108:
        raise ValueError("PayPal-Request-Id must be 1 to 108 characters")
    return key


async def require_pledge(pledge_id: str) -> dict:
    doc = await get_ledger().get_pledge(pledge_id)
    if doc is None:
        raise PledgeNotFound(pledge_id)
    return doc


async def create_pledge(
    *,
    amount_eur: str,
    description: str,
    milestone_id: str,
    client: Any,
    client_key: Optional[str] = None,
    contributor: Optional[str] = None,
) -> dict:
    amount = normalize_amount(amount_eur)
    description = _require_text(description, "description")
    milestone_id = _require_text(milestone_id, "milestone_id")
    key = _client_key(client_key)
    ledger = get_ledger()
    if key:
        existing = await ledger.find_by_client_key(key)
        if existing:
            return existing
    pledge_id = uuid.uuid4().hex
    idempotency_key = key or uuid.uuid4().hex
    order = client.create_authorize_order(
        amount_eur=amount,
        description=description,
        reference_id=pledge_id,
        idempotency_key=idempotency_key,
    )
    order_id = order.get("id")
    if not order_id:
        raise PayPalError(502, "order id missing")
    if key:
        existing = await ledger.find_by_client_key(key)
        if existing:
            return existing
    doc = {
        "_id": pledge_id,
        "client_key": key,
        "status": "created",
        "intent": "AUTHORIZE",
        "currency": "EUR",
        "amount_eur": amount,
        "description": description,
        "milestone_id": milestone_id,
        "contributor": (contributor or "").strip() or None,
        "order_id": order_id,
        "approve_link": approve_link(order),
        "authorization_id": None,
        "authorization_expires_at": None,
        "created_at": now_iso(),
        "history": ["created"],
    }
    saved = await ledger.insert_pledge_once(doc)
    if saved.get("_id") == pledge_id and saved.get("history") == ["created"]:
        await record_finance(
            "pledge_created",
            pledge_id=pledge_id,
            milestone_id=milestone_id,
            amount_eur=amount,
            currency="EUR",
            order_id=order_id,
            status="created",
        )
    return saved


def _require_status(pledge: dict, expected: str, target: str) -> None:
    current = pledge.get("status")
    if current != expected:
        raise IllegalTransition(str(current), target)


async def authorize_pledge(pledge_id: str, client: Any) -> dict:
    pledge = await require_pledge(pledge_id)
    _require_status(pledge, "created", "authorized")
    order = client.authorize_order(pledge["order_id"])
    auth_id, expiration = authorization_from(order)
    pledge["status"] = "authorized"
    pledge["authorization_id"] = auth_id
    pledge["authorization_expires_at"] = expiration or default_expiration()
    pledge["history"] = list(pledge.get("history") or []) + ["authorized"]
    saved = await get_ledger().save_pledge(pledge)
    await record_finance(
        "pledge_authorized",
        pledge_id=saved["_id"],
        milestone_id=saved.get("milestone_id"),
        amount_eur=saved.get("amount_eur"),
        currency="EUR",
        authorization_id=auth_id,
        status="authorized",
    )
    return saved


async def capture_pledge(pledge_id: str, client: Any) -> dict:
    pledge = await require_pledge(pledge_id)
    _require_status(pledge, "authorized", "captured")
    if not pledge.get("authorization_id"):
        raise IllegalTransition("authorized", "captured")
    client.capture_authorization(pledge["authorization_id"])
    pledge["status"] = "captured"
    pledge["history"] = list(pledge.get("history") or []) + ["captured"]
    saved = await get_ledger().save_pledge(pledge)
    from .audit import record
    await record(
        "capture",
        actor="treasurer",
        pledge_id=saved["_id"],
        milestone_id=saved.get("milestone_id"),
        status="captured",
        amount_eur=saved.get("amount_eur"),
        currency="EUR",
    )
    await record_finance(
        "pledge_captured",
        pledge_id=saved["_id"],
        milestone_id=saved.get("milestone_id"),
        amount_eur=saved.get("amount_eur"),
        currency="EUR",
        authorization_id=saved.get("authorization_id"),
        status="captured",
        actor="treasurer",
    )
    return saved


async def void_pledge(pledge_id: str, client: Any) -> dict:
    pledge = await require_pledge(pledge_id)
    _require_status(pledge, "authorized", "voided")
    if not pledge.get("authorization_id"):
        raise IllegalTransition("authorized", "voided")
    client.void_authorization(pledge["authorization_id"])
    pledge["status"] = "voided"
    pledge["history"] = list(pledge.get("history") or []) + ["voided"]
    saved = await get_ledger().save_pledge(pledge)
    from .audit import record
    await record(
        "void",
        actor="treasurer",
        pledge_id=saved["_id"],
        milestone_id=saved.get("milestone_id"),
        status="voided",
        amount_eur=saved.get("amount_eur"),
        currency="EUR",
    )
    await record_finance(
        "pledge_voided",
        pledge_id=saved["_id"],
        milestone_id=saved.get("milestone_id"),
        amount_eur=saved.get("amount_eur"),
        currency="EUR",
        authorization_id=saved.get("authorization_id"),
        status="voided",
        actor="treasurer",
    )
    return saved


async def pledges_for_milestone(milestone_id: str) -> list[dict]:
    return await get_ledger().list_pledges_for_milestone(milestone_id)
