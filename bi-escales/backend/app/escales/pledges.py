"""Pledge state machine: created -> authorized | vaulted -> captured | voided.

AUTHORIZE pledges: created -> authorized -> captured | voided.
VAULT pledges (ESCALES_VAULT_ENABLED): created -> vaulted -> captured | voided.

Nothing is captured or voided until a treasurer calls the matching route.
Forbidden transitions raise ``IllegalTransition`` (HTTP 409 at the edge).
Storage is ``escales_pledges`` when Mongo is configured, otherwise memory.
"""
from __future__ import annotations

import datetime as dt
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from .config import AUTH_MAX_DAYS, vault_cancel_url, vault_return_url
from .ledger import (
    COLLECTIONS,
    get_ledger,
    now_iso,
    record_finance,
    reset_ledger,
)
from .payment_mode import PaymentMode, select_payment_mode
from .paypal_client import (
    PayPalError,
    approve_link,
    authorization_from,
    read_capture_result,
    setup_token_approve_link,
    vault_id_from_token,
)

HONOR_DAYS = 3

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


async def _milestone_arrival(milestone_id: str) -> Optional[str]:
    doc = await get_ledger().get_milestone(milestone_id)
    if not doc:
        return None
    meta = doc.get("meta") or {}
    return meta.get("arrival_iso")


async def resolve_payment_mode(milestone_id: str) -> PaymentMode:
    arrival = await _milestone_arrival(milestone_id)
    return select_payment_mode(arrival)


async def create_pledge(
    *,
    amount_eur: str,
    description: str,
    milestone_id: str,
    client: Any,
    client_key: Optional[str] = None,
    contributor: Optional[str] = None,
    payment_mode: Optional[PaymentMode] = None,
) -> dict:
    amount = normalize_amount(amount_eur)
    description = _require_text(description, "description")
    milestone_id = _require_text(milestone_id, "milestone_id")
    mode = payment_mode or await resolve_payment_mode(milestone_id)
    if mode == "VAULT":
        return await _create_vault_pledge(
            amount=amount,
            description=description,
            milestone_id=milestone_id,
            client=client,
            client_key=client_key,
            contributor=contributor,
        )
    return await _create_authorize_pledge(
        amount=amount,
        description=description,
        milestone_id=milestone_id,
        client=client,
        client_key=client_key,
        contributor=contributor,
    )


async def _create_authorize_pledge(
    *,
    amount: str,
    description: str,
    milestone_id: str,
    client: Any,
    client_key: Optional[str],
    contributor: Optional[str],
) -> dict:
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
        "payment_mode": "AUTHORIZE",
        "currency": "EUR",
        "amount_eur": amount,
        "description": description,
        "milestone_id": milestone_id,
        "contributor": (contributor or "").strip() or None,
        "order_id": order_id,
        "approve_link": approve_link(order),
        "authorization_id": None,
        "authorization_expires_at": None,
        "vault_id": None,
        "setup_token_id": None,
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
            payment_mode="AUTHORIZE",
        )
    return saved


async def _create_vault_pledge(
    *,
    amount: str,
    description: str,
    milestone_id: str,
    client: Any,
    client_key: Optional[str],
    contributor: Optional[str],
) -> dict:
    key = _client_key(client_key)
    ledger = get_ledger()
    if key:
        existing = await ledger.find_by_client_key(key)
        if existing:
            return existing
    pledge_id = uuid.uuid4().hex
    idempotency_key = key or uuid.uuid4().hex
    setup = client.create_setup_token(vault_return_url(), vault_cancel_url())
    setup_id = setup.get("id")
    if not setup_id:
        raise PayPalError(502, "setup token id missing")
    if key:
        existing = await ledger.find_by_client_key(key)
        if existing:
            return existing
    doc = {
        "_id": pledge_id,
        "client_key": key,
        "status": "created",
        "intent": "VAULT",
        "payment_mode": "VAULT",
        "currency": "EUR",
        "amount_eur": amount,
        "description": description,
        "milestone_id": milestone_id,
        "contributor": (contributor or "").strip() or None,
        "order_id": None,
        "approve_link": setup_token_approve_link(setup),
        "authorization_id": None,
        "authorization_expires_at": None,
        "vault_id": None,
        "setup_token_id": str(setup_id),
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
            setup_token_id=str(setup_id),
            status="created",
            payment_mode="VAULT",
        )
    return saved


async def register_vault_pledge(
    pledge_id: str,
    client: Any,
    *,
    setup_token_id: Optional[str] = None,
) -> dict:
    """Exchange an approved setup token for a vaulted payment method (no debit)."""
    pledge = await require_pledge(pledge_id)
    _require_status(pledge, "created", "vaulted")
    if pledge.get("payment_mode") != "VAULT":
        raise IllegalTransition(str(pledge.get("status")), "vaulted")
    stored_token = (pledge.get("setup_token_id") or "").strip()
    if not stored_token:
        raise ValueError("setup_token_id is required")
    supplied = (setup_token_id or "").strip()
    if supplied and supplied != stored_token:
        raise ValueError("setup_token_id does not match this pledge")
    token_id = stored_token
    shown = client.get_setup_token(token_id)
    if str(shown.get("status") or "").upper() != "APPROVED":
        raise ValueError("setup token is not approved")
    payment_token = client.create_payment_token(token_id)
    vault_id = vault_id_from_token(payment_token)
    pledge["status"] = "vaulted"
    pledge["vault_id"] = vault_id
    pledge["setup_token_id"] = token_id
    pledge["history"] = list(pledge.get("history") or []) + ["vaulted"]
    saved = await get_ledger().save_pledge(pledge)
    await record_finance(
        "pledge_vaulted",
        pledge_id=saved["_id"],
        milestone_id=saved.get("milestone_id"),
        amount_eur=saved.get("amount_eur"),
        currency="EUR",
        vault_id=vault_id,
        status="vaulted",
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
    pledge["authorized_at"] = now_iso()
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


def _parse_moment(value: Optional[str]) -> Optional[dt.datetime]:
    text = (value or "").strip()
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
    return moment


def _prepare_authorization_capture(pledge: dict, client: Any) -> None:
    """Reauthorize once the 3-day honor period has passed, and refuse an expired hold."""
    now = dt.datetime.now(dt.timezone.utc)
    expires = _parse_moment(pledge.get("authorization_expires_at"))
    if expires is not None and now >= expires:
        raise ValueError("PayPal authorization has expired")
    authorized_at = _parse_moment(pledge.get("authorized_at"))
    if authorized_at is None or now <= authorized_at + dt.timedelta(days=HONOR_DAYS):
        return
    refreshed = client.reauthorize(pledge["authorization_id"]) or {}
    new_id = refreshed.get("id") or pledge.get("authorization_id")
    pledge["authorization_id"] = str(new_id)
    expiration = refreshed.get("expiration_time")
    if expiration:
        pledge["authorization_expires_at"] = str(expiration)
    pledge["authorized_at"] = now_iso()
    pledge["history"] = list(pledge.get("history") or []) + ["reauthorized"]


async def _finish_capture(pledge: dict, payload: Any, *, finance: dict) -> dict:
    """Record PayPal's capture status. COMPLETED and PENDING are kept; anything else can be retried."""
    from .audit import record

    status, capture_id, order_id = read_capture_result(payload if isinstance(payload, dict) else {})
    if order_id:
        pledge["order_id"] = order_id
    if capture_id:
        pledge["capture_id"] = capture_id
    recorded = status or "MISSING"
    pledge["paypal_status"] = recorded
    mode = finance.get("payment_mode")
    base = {
        "pledge_id": pledge["_id"],
        "milestone_id": pledge.get("milestone_id"),
        "amount_eur": pledge.get("amount_eur"),
        "currency": "EUR",
        "paypal_status": recorded,
        "capture_id": capture_id,
        "actor": "treasurer",
        **finance,
    }
    audit_fields = {
        "actor": "treasurer",
        "pledge_id": pledge["_id"],
        "milestone_id": pledge.get("milestone_id"),
        "amount_eur": pledge.get("amount_eur"),
        "currency": "EUR",
        "paypal_status": recorded,
        "capture_id": capture_id,
    }
    if mode:
        audit_fields["payment_mode"] = mode

    if status == "COMPLETED":
        pledge["status"] = "captured"
        pledge["history"] = list(pledge.get("history") or []) + ["captured"]
        saved = await get_ledger().save_pledge(pledge)
        await record("capture", status="captured", **audit_fields)
        await record_finance("pledge_captured", status="captured", **base)
        return saved
    if status == "PENDING":
        pledge["status"] = "pending"
        pledge["history"] = list(pledge.get("history") or []) + ["pending"]
        saved = await get_ledger().save_pledge(pledge)
        await record("capture", status="pending", **audit_fields)
        await record_finance("pledge_capture_pending", status="pending", **base)
        return saved

    pledge["history"] = list(pledge.get("history") or []) + ["capture_failed"]
    saved = await get_ledger().save_pledge(pledge)
    await record("capture_failed", status=saved.get("status"), **audit_fields)
    await record_finance("pledge_capture_failed", status=saved.get("status"), **base)
    raise ValueError(f"PayPal capture status {recorded} is not COMPLETED or PENDING")


async def capture_pledge(pledge_id: str, client: Any) -> dict:
    pledge = await require_pledge(pledge_id)
    mode = pledge.get("payment_mode") or pledge.get("intent") or "AUTHORIZE"
    if mode == "VAULT":
        _require_status(pledge, "vaulted", "captured")
        vault_id = pledge.get("vault_id")
        if not vault_id:
            raise IllegalTransition("vaulted", "captured")
        payload = client.charge_vaulted(vault_id, pledge["amount_eur"], pledge_id)
        return await _finish_capture(
            pledge,
            payload,
            finance={"vault_id": vault_id, "payment_mode": "VAULT"},
        )
    _require_status(pledge, "authorized", "captured")
    if not pledge.get("authorization_id"):
        raise IllegalTransition("authorized", "captured")
    _prepare_authorization_capture(pledge, client)
    payload = client.capture_authorization(pledge["authorization_id"])
    return await _finish_capture(
        pledge,
        payload,
        finance={"authorization_id": pledge.get("authorization_id")},
    )


async def void_pledge(pledge_id: str, client: Any) -> dict:
    pledge = await require_pledge(pledge_id)
    mode = pledge.get("payment_mode") or pledge.get("intent") or "AUTHORIZE"
    if mode == "VAULT":
        _require_status(pledge, "vaulted", "voided")
        vault_id = pledge.get("vault_id")
        if not vault_id:
            raise IllegalTransition("vaulted", "voided")
        client.delete_payment_token(vault_id)
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
            payment_mode="VAULT",
        )
        await record_finance(
            "pledge_voided",
            pledge_id=saved["_id"],
            milestone_id=saved.get("milestone_id"),
            amount_eur=saved.get("amount_eur"),
            currency="EUR",
            vault_id=vault_id,
            status="voided",
            actor="treasurer",
            payment_mode="VAULT",
        )
        return saved
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
