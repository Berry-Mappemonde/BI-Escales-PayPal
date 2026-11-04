"""Pledge state machine: created -> authorized | vaulted -> captured | voided.

AUTHORIZE pledges: created -> authorized -> captured | voided.
VAULT pledges (ESCALES_VAULT_ENABLED): created -> vaulted -> captured | voided.

Nothing is captured or voided until a treasurer calls the matching route.
Forbidden transitions raise ``IllegalTransition`` (HTTP 409 at the edge).
Storage is ``escales_pledges`` when Mongo is configured, otherwise memory.

``milestone_id`` is where the pledge sits on the route: a stop (``dep-…`` or
``ret-…``) or a cabin leg (``leg-…``). ``target_id`` is what the money is for.
For a stopover kind the target is the bare slug of that same stop. For a cabin
the target is the leg id, the same string as ``milestone_id``. A project pledge
or the common fund may leave ``milestone_id`` empty; the target then defaults
to ``projet`` or ``fonds-commun``.
"""
from __future__ import annotations

import datetime as dt
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
    read_capture_result,
    setup_token_approve_link,
    vault_id_from_token,
    vault_source_from_token,
)

HONOR_DAYS = 3
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
_TARGET_MUST_BE_KNOWN = {"mile", "berth", "night", "meal", "care"}
# Escale kinds and the common fund name this stopover. A project pledge does not.
_TARGET_MUST_MATCH_MILESTONE = _TARGET_MUST_BE_KNOWN | {"common_fund"}
# No stopover required. An empty milestone keeps this default target.
_UNPLACED_TARGET = {"project_pledge": "projet", "common_fund": "fonds-commun"}
# Same figures as the captain catalogue. A mile cannot go under one unit.
_UNIT_FLOOR = {
    "mile": Decimal("1.00"),
    "project_pledge": Decimal("1.00"),
    "berth": Decimal("30.00"),
    "night": Decimal("60.00"),
    "meal": Decimal("60.00"),
    "care": Decimal("40.00"),
    "cabin_leg": Decimal("80.00"),
}
# Fixed tariffs are the catalogue price, not a minimum. A mile stays editable.
_EXACT_PRICE = {
    "berth": Decimal("30.00"),
    "night": Decimal("60.00"),
    "meal": Decimal("60.00"),
    "care": Decimal("40.00"),
    "cabin_leg": Decimal("80.00"),
}


def _target_slug(value: str) -> str:
    from ..escales_names import _slug

    return _slug(value)


async def _known_stopover(slug: str) -> bool:
    """True when the single resolver knows this stopover or leg."""
    if not slug:
        return False
    from .naviguide_bridge import resolve_milestone

    return resolve_milestone(slug) is not None


def _cabin_target(explicit: str, milestone_id: str) -> str:
    """A cabin names the leg milestone. The stored target is that leg id."""
    from .naviguide_bridge import leg_by_id

    chosen = explicit or milestone_id
    if not _TARGET_SLUG.fullmatch(chosen):
        raise ValueError("target_id must match [a-z0-9-]+")
    leg = leg_by_id(chosen)
    if leg is None:
        raise ValueError("target_id must name a cabin leg")
    if milestone_id != leg["id"]:
        raise ValueError("target_id must match the milestone")
    return leg["id"]


def _bare_canonical(milestone_id: str) -> str:
    """Stored target: the route slug, without the ``dep-`` prefix."""
    if milestone_id.startswith("dep-"):
        return milestone_id[4:]
    return milestone_id


async def _resolve_target(target_id: Optional[str], milestone_id: str, kind: str) -> str:
    from .naviguide_bridge import resolve_milestone

    explicit = (target_id or "").strip()
    if kind in _UNPLACED_TARGET and not (milestone_id or "").strip():
        if not explicit:
            return _UNPLACED_TARGET[kind]
        slug = _target_slug(explicit)
        if not slug or not _TARGET_SLUG.fullmatch(slug):
            raise ValueError("target_id must match [a-z0-9-]+")
        resolved = resolve_milestone(explicit)
        return _bare_canonical(resolved) if resolved else slug
    if kind == "cabin_leg":
        return _cabin_target(explicit, milestone_id)
    if explicit and not _TARGET_SLUG.fullmatch(_target_slug(explicit)):
        raise ValueError("target_id must match [a-z0-9-]+")
    milestone_resolved = resolve_milestone(milestone_id)
    explicit_resolved = resolve_milestone(explicit) if explicit else None
    if kind in _TARGET_MUST_MATCH_MILESTONE and explicit:
        if not explicit_resolved or explicit_resolved != milestone_resolved:
            raise ValueError("target_id must match the milestone")
    if kind in _TARGET_MUST_BE_KNOWN:
        chosen = explicit_resolved or milestone_resolved
        if not chosen:
            known = await get_ledger().get_milestone(explicit or milestone_id)
            if known:
                return _bare_canonical(explicit or milestone_id)
            raise ValueError("target_id must name a known stopover")
        return _bare_canonical(chosen)
    if explicit_resolved:
        return _bare_canonical(explicit_resolved)
    if explicit:
        slug = _target_slug(explicit)
        if not slug:
            raise ValueError("target_id must match [a-z0-9-]+")
        return slug
    if milestone_resolved:
        return _bare_canonical(milestone_resolved)
    raise ValueError("target_id must match [a-z0-9-]+")


def _identity(doc: dict) -> dict:
    row = pledge_defaults(doc) or doc
    return {"pledge_kind": row.get("kind"), "target_id": row.get("target_id")}


def finance_milestone_id(pledge: dict) -> str:
    """Journal id for a pledge. A cabin is the leg, not either port."""
    stored = str(pledge.get("milestone_id") or "")
    if str(pledge.get("kind") or "") != "cabin_leg":
        return stored
    from .naviguide_bridge import leg_by_id

    for candidate in (stored, str(pledge.get("target_id") or "")):
        leg = leg_by_id(candidate)
        if leg:
            return str(leg["id"])
    return stored


async def ensure_finance_milestone(pledge: dict, milestone_id: str) -> None:
    """Keep the cabin leg in the ledger so its fund can be read."""
    if str(pledge.get("kind") or "") != "cabin_leg" or not milestone_id:
        return
    from .naviguide_bridge import leg_by_id, leg_milestone_meta

    leg = leg_by_id(milestone_id)
    if leg:
        await get_ledger().ensure_milestone(milestone_id, meta=leg_milestone_meta(leg))


async def record_pledge_captured_once(pledge: dict, *, actor: str) -> bool:
    """One ``pledge_captured`` line per pledge. A webhook and a direct capture share it."""
    from .ledger import list_finance_entries, record_finance

    pledge_id = str(pledge.get("_id") or "")
    if not pledge_id:
        return False
    for entry in await list_finance_entries():
        if entry.get("kind") == "pledge_captured" and entry.get("pledge_id") == pledge_id:
            return False
    milestone_id = finance_milestone_id(pledge)
    await ensure_finance_milestone(pledge, milestone_id)
    await record_finance(
        "pledge_captured",
        pledge_id=pledge_id,
        milestone_id=milestone_id,
        amount_eur=pledge.get("amount_eur"),
        currency=pledge.get("currency") or "EUR",
        status="captured",
        actor=actor,
        **_identity(pledge),
    )
    return True


def _require_text(value: str, field: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _origin_of(raw: str) -> str:
    parts = urlsplit((raw or "").strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}".rstrip("/")


def _allowed_return_origins(caller_origin: Optional[str] = None) -> set[str]:
    """CORS list, plus ESCALES_PUBLIC_URL and the origin serving this request."""
    import os

    from .config import PUBLIC_API_ORIGIN, cors_origins, public_base_url

    allowed = {item.rstrip("/") for item in cors_origins()}
    for raw in (
        public_base_url(),
        os.environ.get("ESCALES_PUBLIC_URL") or "",
        PUBLIC_API_ORIGIN,
        caller_origin or "",
    ):
        origin = _origin_of(raw)
        if origin:
            allowed.add(origin)
    return allowed


def _http_url(
    raw: Optional[str],
    fallback: str,
    field: str,
    *,
    caller_origin: Optional[str] = None,
) -> str:
    text = (raw or "").strip() or fallback
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"{field} must be an http(s) URL")
    if field in {"return_url", "cancel_url"}:
        origin = f"{parts.scheme}://{parts.netloc}".rstrip("/")
        if origin not in _allowed_return_origins(caller_origin):
            raise ValueError(f"{field} must use an allowed frontend origin")
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
    """True when PayPal shows APPROVED or COMPLETED.

    A client without ``get_order`` cannot say, so the older fakes still pass.
    An empty status fails closed: the order is not treated as approved.
    """
    getter = getattr(client, "get_order", None)
    if getter is None or not order_id:
        return True
    current = getter(order_id) or {}
    status = str(current.get("status") or "").strip().upper()
    if not status:
        return False
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
    caller_origin: Optional[str] = None,
) -> dict:
    amount = normalize_amount(amount_eur)
    description = _require_text(description, "description")
    pledge_kind = _kind(kind)
    exact = _EXACT_PRICE.get(pledge_kind)
    if exact is not None and Decimal(amount) != exact:
        raise ValueError(f"{pledge_kind} amount must be {exact:.2f} EUR")
    floor = _UNIT_FLOOR.get(pledge_kind)
    if exact is None and floor is not None and Decimal(amount) < floor:
        raise ValueError(f"{pledge_kind} amount must be at least {floor:.2f} EUR")
    if pledge_kind in _UNPLACED_TARGET and not (milestone_id or "").strip():
        milestone_id = ""
    else:
        milestone_id = _require_text(milestone_id, "milestone_id")
    replay_key = _client_key(client_key)
    if replay_key:
        existing = await get_ledger().find_by_client_key(replay_key)
        if existing:
            return existing
    from .naviguide_bridge import leg_departing_from, resolve_milestone

    if pledge_kind in _UNPLACED_TARGET and milestone_id == "":
        canonical = ""
    else:
        canonical = resolve_milestone(milestone_id)
        if canonical is None:
            known = await get_ledger().get_milestone(milestone_id)
            if known:
                canonical = milestone_id
        if pledge_kind == "cabin_leg" and canonical and not str(canonical).startswith("leg-"):
            leg = leg_departing_from(canonical)
            if leg:
                canonical = str(leg["id"])
        if not canonical:
            raise ValueError("milestone_id must name a known stopover")
        milestone_id = str(canonical)
    resolved_target = await _resolve_target(target_id, milestone_id, pledge_kind)
    # A cabin is always an authorization. Capture waits for the departure.
    if pledge_kind == "cabin_leg":
        mode = "AUTHORIZE"
        from .naviguide_bridge import leg_by_id, leg_milestone_meta

        leg = leg_by_id(resolved_target)
        if leg:
            await get_ledger().ensure_milestone(leg["id"], meta=leg_milestone_meta(leg))
    else:
        mode = payment_mode or await resolve_payment_mode(milestone_id)
    from .departure_clock import refuse_cancelled_departure, refuse_early_authorization

    draft = {
        "milestone_id": milestone_id,
        "kind": pledge_kind,
        "target_id": resolved_target,
    }
    await refuse_cancelled_departure(draft)
    # An authorization lasts 29 days. Refuse before PayPal creates the order.
    # A vault setup is not an authorization and stays open.
    if mode != "VAULT":
        await refuse_early_authorization(draft)
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
        caller_origin=caller_origin,
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
    caller_origin: Optional[str] = None,
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
        _http_url(return_url, order_return_url(), "return_url", caller_origin=caller_origin),
        pledge_id,
        "return",
    )
    cancel = _callback_url(
        _http_url(cancel_url, order_cancel_url(), "cancel_url", caller_origin=caller_origin),
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
    stored_token = (pledge.get("setup_token_id") or "").strip()
    if not stored_token:
        raise ValueError("setup_token_id is required")
    supplied = (setup_token_id or "").strip()
    if supplied and supplied != stored_token:
        raise ValueError("setup_token_id does not match this pledge")
    token_id = stored_token
    shown = client.get_setup_token(token_id)
    if str((shown or {}).get("status") or "").upper() != "APPROVED":
        raise ValueError("setup token is not approved")
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
    from .departure_clock import refuse_cancelled_departure

    await refuse_cancelled_departure(pledge)
    order = client.authorize_order(order_id)
    auth_id, expiration = authorization_from(order)
    pledge["status"] = "authorized"
    pledge["authorized_at"] = now_iso()
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
    milestone_id = finance_milestone_id(pledge)
    await ensure_finance_milestone(pledge, milestone_id)
    base = {
        "pledge_id": pledge["_id"],
        "milestone_id": milestone_id,
        "amount_eur": pledge.get("amount_eur"),
        "currency": "EUR",
        "paypal_status": recorded,
        "capture_id": capture_id,
        "actor": "treasurer",
        **finance,
        **_identity(pledge),
    }
    audit_fields = {
        "actor": "treasurer",
        "pledge_id": pledge["_id"],
        "milestone_id": milestone_id,
        "amount_eur": pledge.get("amount_eur"),
        "currency": "EUR",
        "paypal_status": recorded,
        "capture_id": capture_id,
        **_identity(pledge),
    }
    if mode:
        audit_fields["payment_mode"] = mode

    if status == "COMPLETED":
        pledge["status"] = "captured"
        pledge["history"] = list(pledge.get("history") or []) + ["captured"]
        saved = await get_ledger().save_pledge(pledge)
        await record("capture", status="captured", **audit_fields)
        await record_pledge_captured_once(saved, actor="treasurer")
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
        payload = client.charge_vaulted(
            vault_id,
            pledge["amount_eur"],
            pledge_id,
            source=pledge.get("vault_source") or "paypal",
        )
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


def _stamp_void(pledge: dict, payload: Any, fallback_id: str) -> None:
    """PayPal's void id when the body has one, otherwise the hold we released."""
    body = payload if isinstance(payload, dict) else {}
    void_id = str(body.get("id") or "").strip() or str(fallback_id or "").strip()
    if not void_id:
        raise PayPalError(502, "void id missing")
    pledge["void_id"] = void_id
    pledge["voided_at"] = now_iso()
    pledge["status"] = "voided"
    pledge["history"] = list(pledge.get("history") or []) + ["voided"]


async def void_pledge(pledge_id: str, client: Any) -> dict:
    pledge = await require_pledge(pledge_id)
    mode = pledge.get("payment_mode") or pledge.get("intent") or "AUTHORIZE"
    if mode == "VAULT":
        _require_status(pledge, "vaulted", "voided")
        vault_id = pledge.get("vault_id")
        if not vault_id:
            raise IllegalTransition("vaulted", "voided")
        released = client.delete_payment_token(vault_id)
        _stamp_void(pledge, released, str(vault_id))
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
            void_id=saved.get("void_id"),
            voided_at=saved.get("voided_at"),
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
            void_id=saved.get("void_id"),
            voided_at=saved.get("voided_at"),
            **_identity(saved),
        )
        return saved
    _require_status(pledge, "authorized", "voided")
    if not pledge.get("authorization_id"):
        raise IllegalTransition("authorized", "voided")
    released = client.void_authorization(pledge["authorization_id"])
    _stamp_void(pledge, released, str(pledge["authorization_id"]))
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
        void_id=saved.get("void_id"),
        voided_at=saved.get("voided_at"),
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
        void_id=saved.get("void_id"),
        voided_at=saved.get("voided_at"),
        **_identity(saved),
    )
    return saved


async def pledges_for_milestone(milestone_id: str) -> list[dict]:
    from .naviguide_bridge import resolve_milestone

    canonical = resolve_milestone(milestone_id) or milestone_id
    rows = await get_ledger().list_pledges_for_milestone(canonical)
    if canonical == milestone_id:
        return rows
    seen = {row.get("_id") for row in rows}
    for row in await get_ledger().list_pledges_for_milestone(milestone_id):
        if row.get("_id") not in seen:
            rows.append(row)
    return rows
