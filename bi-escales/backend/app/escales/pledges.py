"""Pledge state machine: created -> authorized | vaulted -> captured | voided.

AUTHORIZE pledges: created -> authorized -> captured | voided.
VAULT pledges (ESCALES_VAULT_ENABLED): created -> vaulted -> captured | voided.

Nothing is captured or voided until a treasurer calls the matching route.
Forbidden transitions raise ``IllegalTransition`` (HTTP 409 at the edge).
Storage is ``escales_pledges`` when Mongo is configured, otherwise memory.
"""
from __future__ import annotations

import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .config import AUTH_MAX_DAYS, order_cancel_url, order_return_url, vault_cancel_url, vault_return_url
from .ledger import (
    COLLECTIONS,
    get_ledger,
    now_iso,
    pledge_defaults,
    record_finance,
    reset_ledger,
)
from .payment_mode import PaymentMode, select_payment_mode
from .paypal_client import (
    PayPalError,
    approve_link,
    authorization_from,
    setup_token_approve_link,
    vault_id_from_token,
    vault_source_from_token,
)

PLEDGES_COLLECTION = "escales_pledges"
MILESTONES_COLLECTION = "escales_milestones"
AUDIT_COLLECTION = "escales_audit"

_AMOUNT = re.compile(r"^\d+(?:\.\d{1,2})?$")

# Même liste pour la création, le catalogue et l'API. ``mile`` est le défaut.
PLEDGE_KINDS = (
    "mile",
    "project_pledge",
    "berth",
    "night",
    "meal",
    "care",
    "cabin_leg",
    "common_fund",
)


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
    row = pledge_defaults(doc) or doc
    hidden = {"_id", "client_key"}
    out = {key: value for key, value in row.items() if key not in hidden}
    out["id"] = doc["_id"]
    return out


def _kind(raw: Optional[str]) -> str:
    if raw is None or not str(raw).strip():
        return "mile"
    kind = str(raw).strip().lower()
    if kind not in PLEDGE_KINDS:
        raise ValueError("kind must be one of: " + ", ".join(PLEDGE_KINDS))
    return kind


_TARGET_SLUG = re.compile(r"^[a-z0-9-]+$")
_TARGET_MUST_BE_KNOWN = {"mile", "berth", "night", "meal", "care", "cabin_leg"}
# Escale kinds and the common fund name this stopover. A project pledge does not.
_TARGET_MUST_MATCH_MILESTONE = _TARGET_MUST_BE_KNOWN | {"common_fund"}


def _target_slug(value: str) -> str:
    from ..escales_names import _slug

    return _slug(value)


async def _known_stopover(slug: str) -> bool:
    """True when the slug is a stopover we already show or store."""
    if not slug:
        return False
    from ..escales_names import ESCALE_DISPLAY_NAMES
    from .captain import _CANONICAL_DISPLAY
    from .naviguide_bridge import local_schedule_export

    if slug in ESCALE_DISPLAY_NAMES or slug in _CANONICAL_DISPLAY:
        return True
    for item in local_schedule_export().get("escales") or []:
        if not isinstance(item, dict):
            continue
        for raw in (item.get("slug"), item.get("milestone_id"), item.get("name")):
            if _target_slug(str(raw or "")) == slug:
                return True
    for candidate in (slug, f"dep-{slug}"):
        if await get_ledger().get_milestone(candidate):
            return True
    return False


async def _resolve_target(target_id: Optional[str], milestone_id: str, kind: str) -> str:
    explicit = (target_id or "").strip()
    if explicit and not _TARGET_SLUG.fullmatch(explicit):
        raise ValueError("target_id must match [a-z0-9-]+")
    chosen = explicit or milestone_id
    slug = _target_slug(chosen)
    if kind in _TARGET_MUST_MATCH_MILESTONE and slug != _target_slug(milestone_id):
        raise ValueError("target_id must match the milestone")
    if kind in _TARGET_MUST_BE_KNOWN and not await _known_stopover(slug):
        raise ValueError("target_id must name a known stopover")
    return chosen if explicit else milestone_id


def _identity(doc: dict) -> dict:
    row = pledge_defaults(doc) or doc
    return {"pledge_kind": row.get("kind"), "target_id": row.get("target_id")}


def _require_text(value: str, field: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _http_url(raw: Optional[str], fallback: str, field: str) -> str:
    text = (raw or "").strip() or fallback
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"{field} must be an http(s) URL")
    return text


def _callback_url(base: str, pledge_id: str, flag: str) -> str:
    """PayPal return or cancel URL, with the pledge id the page authorizes."""
    parts = urlsplit(base)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["paypal"] = flag
    query["pledge_id"] = pledge_id
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _create_authorize_order(client: Any, **kwargs: Any) -> dict:
    """Pass return URLs when the client accepts them. Older fakes do not."""
    try:
        return client.create_authorize_order(**kwargs)
    except TypeError as exc:
        message = str(exc)
        if "return_url" not in message and "cancel_url" not in message:
            raise
        slim = {key: value for key, value in kwargs.items() if key not in {"return_url", "cancel_url"}}
        return client.create_authorize_order(**slim)


def _buyer_approved(client: Any, order_id: str) -> bool:
    """True when PayPal already shows the buyer approved, or the client cannot say."""
    getter = getattr(client, "get_order", None)
    if getter is None or not order_id:
        return True
    current = getter(order_id) or {}
    status = str(current.get("status") or "").upper()
    if not status:
        return True
    return status in {"APPROVED", "COMPLETED"}


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
    kind: Optional[str] = None,
    target_id: Optional[str] = None,
    return_url: Optional[str] = None,
    cancel_url: Optional[str] = None,
) -> dict:
    amount = normalize_amount(amount_eur)
    description = _require_text(description, "description")
    milestone_id = _require_text(milestone_id, "milestone_id")
    replay_key = _client_key(client_key)
    if replay_key:
        existing = await get_ledger().find_by_client_key(replay_key)
        if existing:
            return existing
    pledge_kind = _kind(kind)
    resolved_target = await _resolve_target(target_id, milestone_id, pledge_kind)
    mode = payment_mode or await resolve_payment_mode(milestone_id)
    if mode == "VAULT":
        return await _create_vault_pledge(
            amount=amount,
            description=description,
            milestone_id=milestone_id,
            client=client,
            client_key=client_key,
            contributor=contributor,
            kind=pledge_kind,
            target_id=resolved_target,
        )
    return await _create_authorize_pledge(
        amount=amount,
        description=description,
        milestone_id=milestone_id,
        client=client,
        client_key=client_key,
        contributor=contributor,
        kind=pledge_kind,
        target_id=resolved_target,
        return_url=return_url,
        cancel_url=cancel_url,
    )


async def _create_authorize_pledge(
    *,
    amount: str,
    description: str,
    milestone_id: str,
    client: Any,
    client_key: Optional[str],
    contributor: Optional[str],
    kind: str,
    target_id: str,
    return_url: Optional[str] = None,
    cancel_url: Optional[str] = None,
) -> dict:
    key = _client_key(client_key)
    ledger = get_ledger()
    if key:
        existing = await ledger.find_by_client_key(key)
        if existing:
            return existing
    pledge_id = uuid.uuid4().hex
    idempotency_key = key or uuid.uuid4().hex
    back = _callback_url(
        _http_url(return_url, order_return_url(), "return_url"),
        pledge_id,
        "return",
    )
    cancel = _callback_url(
        _http_url(cancel_url, order_cancel_url(), "cancel_url"),
        pledge_id,
        "cancel",
    )
    order = _create_authorize_order(
        client,
        amount_eur=amount,
        description=description,
        reference_id=pledge_id,
        idempotency_key=idempotency_key,
        return_url=back,
        cancel_url=cancel,
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
        "kind": kind,
        "target_id": target_id,
        "contributor": (contributor or "").strip() or None,
        "order_id": order_id,
        "approve_link": approve_link(order),
        "authorization_id": None,
        "authorization_expires_at": None,
        "vault_id": None,
        "vault_source": None,
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
            pledge_kind=kind,
            target_id=target_id,
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
    kind: str,
    target_id: str,
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
        "kind": kind,
        "target_id": target_id,
        "contributor": (contributor or "").strip() or None,
        "order_id": None,
        "approve_link": setup_token_approve_link(setup),
        "authorization_id": None,
        "authorization_expires_at": None,
        "vault_id": None,
        "vault_source": None,
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
            pledge_kind=kind,
            target_id=target_id,
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
    token_id = (setup_token_id or pledge.get("setup_token_id") or "").strip()
    if not token_id:
        raise ValueError("setup_token_id is required")
    payment_token = client.create_payment_token(token_id)
    vault_id = vault_id_from_token(payment_token)
    pledge["status"] = "vaulted"
    pledge["vault_id"] = vault_id
    pledge["vault_source"] = vault_source_from_token(payment_token)
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
        **_identity(saved),
    )
    return saved


def _require_status(pledge: dict, expected: str, target: str) -> None:
    current = pledge.get("status")
    if current != expected:
        raise IllegalTransition(str(current), target)


async def authorize_pledge(pledge_id: str, client: Any) -> dict:
    pledge = await require_pledge(pledge_id)
    _require_status(pledge, "created", "authorized")
    order_id = str(pledge.get("order_id") or "")
    if not _buyer_approved(client, order_id):
        raise IllegalTransition(str(pledge.get("status")), "authorized")
    order = client.authorize_order(order_id)
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
        **_identity(saved),
    )
    return saved


async def capture_pledge(pledge_id: str, client: Any) -> dict:
    pledge = await require_pledge(pledge_id)
    mode = pledge.get("payment_mode") or pledge.get("intent") or "AUTHORIZE"
    if mode == "VAULT":
        _require_status(pledge, "vaulted", "captured")
        vault_id = pledge.get("vault_id")
        if not vault_id:
            raise IllegalTransition("vaulted", "captured")
        client.charge_vaulted(
            vault_id,
            pledge["amount_eur"],
            pledge_id,
            source=pledge.get("vault_source") or "paypal",
        )
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
            payment_mode="VAULT",
            **_identity(saved),
        )
        await record_finance(
            "pledge_captured",
            pledge_id=saved["_id"],
            milestone_id=saved.get("milestone_id"),
            amount_eur=saved.get("amount_eur"),
            currency="EUR",
            vault_id=vault_id,
            status="captured",
            actor="treasurer",
            payment_mode="VAULT",
            **_identity(saved),
        )
        return saved
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
        **_identity(saved),
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
        **_identity(saved),
    )
    return saved


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
            **_identity(saved),
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
            **_identity(saved),
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
        **_identity(saved),
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
        **_identity(saved),
    )
    return saved


async def pledges_for_milestone(milestone_id: str) -> list[dict]:
    return await get_ledger().list_pledges_for_milestone(milestone_id)
