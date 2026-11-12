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

Capture timing (7488f15): stop-level pledges on boat arrival at the stop (void if
cancelled); cabin legs on leg departure; common fund at once (treasurer, not the clock).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import logging
import re
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from .config import (
    AUTH_MAX_DAYS,
    order_cancel_url,
    order_return_url,
    simulated_now,
    vault_cancel_url,
    vault_enabled,
    vault_return_url,
)
from .ledger import (
    COLLECTIONS,
    get_ledger,
    now_iso,
    pledge_defaults,
    record_finance,
    reset_ledger,
)
from .payment_mode import PaymentMode
from .paypal_client import (
    PayPalError,
    adopted_authorization_mismatch,
    approve_link,
    authorization_from,
    paypal_error_has_issue,
    read_capture_result,
    setup_token_approve_link,
    usable_authorization_from_order,
    vault_id_from_order,
    vault_id_from_token,
    vault_source_from_token,
)

HONOR_DAYS = 3
STOP_GIFT_MAX_EUR = Decimal("1000.00")
log = logging.getLogger(__name__)
_authorize_guard = asyncio.Lock()
_authorize_locks: dict[str, asyncio.Lock] = {}


@asynccontextmanager
async def _serialize_pledge_authorize(pledge_id: str):
    async with _authorize_guard:
        lock = _authorize_locks.get(pledge_id)
        if lock is None:
            lock = asyncio.Lock()
            _authorize_locks[pledge_id] = lock
    async with lock:
        yield


def _normalize_refunds(pledge: dict) -> list[dict]:
    rows = pledge.get("refunds")
    if isinstance(rows, list) and rows:
        return [dict(row) for row in rows if isinstance(row, dict)]
    legacy_id = str(pledge.get("refund_id") or "").strip()
    legacy_amount = str(pledge.get("refunded_amount_eur") or "").strip()
    if legacy_id and legacy_amount:
        return [{
            "id": legacy_id,
            "amount": legacy_amount,
            "key": "",
            "status": "COMPLETED",
            "at": str(pledge.get("refunded_at") or now_iso()),
        }]
    return []


def refunded_amount_from_pledge(pledge: dict) -> Decimal:
    """Sum of unique refund ids with COMPLETED or PENDING status."""
    seen: set[str] = set()
    total = Decimal("0.00")
    for row in _normalize_refunds(pledge):
        refund_id = str(row.get("id") or "").strip()
        if not refund_id or refund_id in seen:
            continue
        status = str(row.get("status") or "COMPLETED").upper()
        if status not in {"COMPLETED", "PENDING", "REFUNDED"}:
            continue
        seen.add(refund_id)
        total += Decimal(str(row.get("amount") or "0"))
    return total


def _append_refund_row(refunds: list[dict], row: dict) -> list[dict]:
    refund_id = str(row.get("id") or "").strip()
    if not refund_id:
        return refunds
    if any(str(existing.get("id") or "") == refund_id for existing in refunds):
        return refunds
    return [*refunds, row]


def _refund_amount_idempotency_key(pledge_id: str, refund_value: str) -> str:
    key = f"refund-{pledge_id}-{refund_value}"
    if len(key) > 108:
        return key[:108]
    return key


def _refund_request_idempotency_key(pledge_id: str, request_key: str) -> str:
    raw = str(request_key or "").strip()
    if not raw:
        raise ValueError("request_key must not be empty")
    key = f"refund-{pledge_id}-{raw}"
    resolved = _client_key(key)
    return resolved if resolved is not None else key


def _refund_row_for_paypal_id(pledge: dict, refund_id: str) -> Optional[dict]:
    needle = str(refund_id or "").strip()
    if not needle:
        return None
    for row in _normalize_refunds(pledge):
        if str(row.get("id") or "").strip() != needle:
            continue
        status = str(row.get("status") or "COMPLETED").upper()
        if status in {"COMPLETED", "PENDING", "REFUNDED"}:
            return row
    return None


def _refund_row_for_key(pledge: dict, key: str) -> Optional[dict]:
    needle = str(key or "").strip()
    if not needle:
        return None
    for row in _normalize_refunds(pledge):
        if str(row.get("key") or "").strip() != needle:
            continue
        status = str(row.get("status") or "COMPLETED").upper()
        if status in {"COMPLETED", "PENDING", "REFUNDED"}:
            return row
    return None


async def _finish_idempotent_refund(pledge_id: str, pledge: dict) -> dict:
    """Return pledge after a refund intent is already satisfied (webhook or prior API)."""
    if pledge.get("pending_refund"):
        pledge.pop("pending_refund", None)
        pledge = await get_ledger().save_pledge(pledge)
    fresh = await get_ledger().get_pledge(pledge_id)
    if fresh is None:
        raise PledgeNotFound(pledge_id)
    return fresh


def _is_transport_retry(exc: Exception) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, PayPalError) and exc.status >= 500:
        body = exc.body
        if body is None or body == "" or body == {}:
            return True
    return False


async def _persist_capture_attempt(pledge: dict) -> str:
    pledge_id = str(pledge.get("_id") or "")
    attempt = int(pledge.get("capture_attempt") or 1)
    if attempt < 1:
        attempt = 1
    pledge["capture_attempt"] = attempt
    key = f"capture-{pledge_id}-{attempt}"
    pledge["capture_idempotency_key"] = key
    return key


async def _record_capture_attempt_outcome(pledge: dict, payload: dict) -> None:
    status, _, _ = read_capture_result(payload if isinstance(payload, dict) else {})
    recorded = str(status or "").upper()
    pledge["last_capture_status"] = recorded
    if recorded and recorded not in {"COMPLETED", "PENDING"}:
        attempt = int(pledge.get("capture_attempt") or 1)
        pledge["capture_attempt"] = attempt + 1


async def _call_with_capture_idempotency(
    pledge: dict,
    call: Callable[[str], dict],
) -> tuple[dict, dict]:
    key = await _persist_capture_attempt(pledge)
    saved = await get_ledger().save_pledge(pledge)
    try:
        payload = await asyncio.to_thread(call, key)
    except Exception as exc:
        if _is_transport_retry(exc):
            raise
        raise
    await _record_capture_attempt_outcome(saved, payload)
    saved = await get_ledger().save_pledge(saved)
    return saved, payload


async def reconcile_refund_on_pledge(
    pledge: dict,
    *,
    refund_id: str,
    amount_eur: str,
    status: str = "COMPLETED",
    key: str = "",
    at: Optional[str] = None,
    refund_payload: Optional[dict] = None,
) -> dict:
    """Merge one PayPal refund id into ``pledge["refunds"]`` (webhook or API)."""
    stored_status = str(status or "COMPLETED").upper()
    if stored_status == "REFUNDED":
        stored_status = "COMPLETED"
    refund_row = {
        "id": str(refund_id),
        "amount": amount_eur,
        "key": key,
        "status": stored_status,
        "at": at or now_iso(),
    }
    from .paypal_settlement import enrich_refund_row_settlement, recompute_received_net_eur

    refund_row = enrich_refund_row_settlement(pledge, refund_payload, refund_row)
    existing = _normalize_refunds(pledge)
    refunds = _append_refund_row(existing, refund_row)
    if refunds is existing and any(str(r.get("id") or "") == str(refund_id) for r in existing):
        for index, row in enumerate(refunds):
            if str(row.get("id") or "") != str(refund_id):
                continue
            merged = dict(row)
            for field, value in refund_row.items():
                if value not in (None, "") and merged.get(field) in (None, ""):
                    merged[field] = value
            refunds[index] = merged
            break
    pledge["refunds"] = refunds
    recompute_received_net_eur(pledge, refunds)
    total = refunded_amount_from_pledge(pledge)
    pledge["refunded_amount_eur"] = f"{total:.2f}"
    capture_total = Decimal(str(pledge.get("amount_eur") or "0"))
    if total >= capture_total:
        pledge["status"] = "refunded"
    elif total > Decimal("0"):
        pledge["status"] = "partially_refunded"
    if refunds:
        pledge["refund_id"] = str(refunds[-1].get("id") or "")
    if at and not str(pledge.get("refunded_at") or "").strip():
        pledge["refunded_at"] = at
    elif at and total >= capture_total:
        pledge["refunded_at"] = at
    pledge.pop("pending_refund", None)
    return await get_ledger().save_pledge(pledge)


def sponsor_customer_id(pledge_id: str, contributor: Optional[str]) -> str:
    """Stable PayPal Vault customer.id (PayPal max length 22)."""
    label = (contributor or "").strip().lower()
    if label:
        digest = hashlib.sha256(label.encode("utf-8")).hexdigest()[:21]
        return f"s{digest}"
    pid = str(pledge_id or "").strip()
    return f"p{pid[:21]}"


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
    "stop_gift",
)


class IllegalTransition(Exception):
    def __init__(self, current: str, target: str):
        self.current = current
        self.target = target
        super().__init__(f"forbidden transition {current} -> {target}")


class RefundRequestKeyRequired(Exception):
    """Another refund of the same amount needs an explicit request_key."""

    def __init__(self) -> None:
        super().__init__(
            "another refund of this amount requires request_key; "
            "send a unique request_key per refund action"
        )


class PledgeAlreadyFullyRefunded(Exception):
    """Refund requested after the capture is already fully reversed."""

    def __init__(self, paypal_refund_id: str = "") -> None:
        self.paypal_refund_id = str(paypal_refund_id or "").strip()
        super().__init__("pledge already fully refunded")


def _ledger_paypal_refund_id(pledge: dict) -> str:
    """Latest PayPal refund resource id stored on the pledge ledger row."""
    for row in reversed(_normalize_refunds(pledge)):
        rid = str(row.get("id") or "").strip()
        if rid:
            return rid
    return str(pledge.get("refund_id") or "").strip()


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
_TARGET_MUST_BE_KNOWN = {"mile", "berth", "night", "meal", "care", "stop_gift"}
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
    if kind == "stop_gift":
        from .departure_clock import arrival_milestone
        arrival = await arrival_milestone(
            {"kind": kind, "milestone_id": milestone_id}, read_only=True,
        )
        if arrival is None:
            raise ValueError("stop_gift requires a known stop arrival milestone")
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


async def record_pledge_captured_once(pledge: dict, *, actor: str, client: Any = None) -> dict:
    """One ``pledge_captured`` line per pledge. Berth captures may trigger marina payout."""
    from .ledger import list_finance_entries, record_finance
    from .marina_berth_settlement import apply_marina_berth_settlement

    from .marina_berth_settlement import marina_settlement_done

    pledge_id = str(pledge.get("_id") or "")
    if not pledge_id:
        return pledge
    for entry in await list_finance_entries():
        if entry.get("kind") == "pledge_captured" and entry.get("pledge_id") == pledge_id:
            # Already journaled: only retry an unfinished marina payout (retry-safe).
            if marina_settlement_done(pledge):
                return pledge
            settled = await apply_marina_berth_settlement(pledge, actor=actor, client=client)
            return await get_ledger().save_pledge(settled)
    milestone_id = finance_milestone_id(pledge)
    await ensure_finance_milestone(pledge, milestone_id)
    at = str(pledge.get("captured_at") or "").strip() or now_iso()
    from .paypal_settlement import settlement_finance_fields

    await record_finance(
        "pledge_captured",
        pledge_id=pledge_id,
        milestone_id=milestone_id,
        amount_eur=pledge.get("amount_eur"),
        currency=pledge.get("currency") or "EUR",
        status="captured",
        actor=actor,
        at=at,
        capture_id=pledge.get("capture_id"),
        **_identity(pledge),
        **settlement_finance_fields(pledge),
    )
    pledge = await apply_marina_berth_settlement(pledge, actor=actor, client=client)
    if pledge.get("platform_fee_eur") or pledge.get("marina_payout_batch_id") or pledge.get("marina_payout_status"):
        pledge = await get_ledger().save_pledge(pledge)
    return pledge


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


def _vault_callback_url(base: str, pledge_id: str, flag: str) -> str:
    """Vault setup return or cancel URL, with the pledge id the page registers."""
    parts = urlsplit(base)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["vault"] = flag
    query["pledge_id"] = pledge_id
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _create_authorize_order(client: Any, **kwargs: Any) -> dict:
    """Pass return URLs when the client accepts them. Older fakes do not."""
    try:
        return client.create_authorize_order(**kwargs)
    except TypeError as exc:
        message = str(exc)
        if not any(
            token in message
            for token in (
                "return_url",
                "cancel_url",
                "checkout_locale",
                "payee_merchant_id",
                "platform_fee_eur",
                "platform_merchant_id",
            )
        ):
            raise
        slim = {
            key: value
            for key, value in kwargs.items()
            if key
            not in {
                "return_url",
                "cancel_url",
                "checkout_locale",
                "payee_merchant_id",
                "platform_fee_eur",
                "platform_merchant_id",
            }
        }
        return client.create_authorize_order(**slim)


def _create_capture_order(client: Any, **kwargs: Any) -> dict:
    create = getattr(client, "create_capture_order", None)
    if create is None:
        raise PayPalError(502, "capture checkout unavailable")
    try:
        return create(**kwargs)
    except TypeError as exc:
        message = str(exc)
        if not any(token in message for token in ("return_url", "cancel_url", "checkout_locale")):
            raise
        slim = {
            key: value
            for key, value in kwargs.items()
            if key not in {"return_url", "cancel_url", "checkout_locale", "currency_code"}
        }
        return create(**slim)


def _create_authorize_vault_order(client: Any, **kwargs: Any) -> dict:
    create = getattr(client, "create_authorize_vault_order", None)
    if create is None:
        raise PayPalError(502, "vault-on-purchase unavailable")
    try:
        return create(**kwargs)
    except TypeError as exc:
        message = str(exc)
        if "checkout_locale" not in message:
            raise
        slim = {key: value for key, value in kwargs.items() if key != "checkout_locale"}
        return create(**slim)


def _normalize_checkout_method(raw: Optional[str]) -> str:
    token = (raw or "wallet").strip().lower()
    if token not in {"wallet", "card"}:
        raise ValueError("checkout_method must be wallet or card")
    return token


def _create_card_authorize_order(client: Any, **kwargs: Any) -> dict:
    create = getattr(client, "create_card_authorize_order", None)
    if create is None:
        raise PayPalError(502, "card checkout unavailable")
    try:
        return create(**kwargs)
    except TypeError as exc:
        message = str(exc)
        if "checkout_locale" not in message:
            raise
        slim = {key: value for key, value in kwargs.items() if key != "checkout_locale"}
        return create(**slim)


def _create_card_setup_token(client: Any, **kwargs: Any) -> dict:
    create = getattr(client, "create_card_setup_token", None)
    if create is None:
        raise PayPalError(502, "card vault setup unavailable")
    try:
        return create(**kwargs)
    except TypeError as exc:
        message = str(exc)
        if "checkout_locale" not in message:
            raise
        slim = {key: value for key, value in kwargs.items() if key != "checkout_locale"}
        return create(**slim)


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


async def resolve_payment_mode(milestone_id: str) -> PaymentMode:
    """AUTHORIZE when departure is within 29 days; otherwise VAULT when enabled."""
    from .config import vault_enabled
    from .departure_clock import refuse_early_authorization
    from .naviguide_bridge import resolve_schedule_milestone

    if not vault_enabled():
        return "AUTHORIZE"
    await resolve_schedule_milestone(milestone_id)
    draft = {"milestone_id": milestone_id, "kind": "mile"}
    try:
        await refuse_early_authorization(draft)
    except ValueError:
        return "VAULT"
    return "AUTHORIZE"


async def create_pledge(*, quantity: Optional[int] = None, **kwargs: Any) -> dict:
    """Validate explicit unit quantities before any PayPal side effect."""
    kind = _kind(kwargs.get("kind"))
    if quantity is not None:
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 1000:
            raise ValueError("quantity must be an integer between 1 and 1000")
        unit = _UNIT_FLOOR.get(kind) if kind != "project_pledge" else None
        if unit is None:
            raise ValueError("quantity is only supported for per-unit pledges")
        expected = unit * quantity
        if Decimal(normalize_amount(kwargs["amount_eur"])) != expected:
            raise ValueError(f"amount must match unit price × quantity ({expected:.2f} EUR)")
        kwargs["amount_eur"] = f"{expected:.2f}"
    saved = await _create_pledge(quantity=quantity, **kwargs)
    if (quantity is not None and saved.get("quantity") is None
            and saved.get("kind") == kind and Decimal(saved["amount_eur"]) == expected):
        saved["quantity"] = quantity
        saved = await get_ledger().save_pledge(saved)
    return saved


async def _create_pledge(
    *,
    quantity: Optional[int] = None,
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
    checkout_locale: Optional[str] = None,
    checkout_method: Optional[str] = None,
) -> dict:
    raw_amount = amount_eur
    description = _require_text(description, "description")
    pledge_kind = _kind(kind)
    amount: Optional[str] = None
    if pledge_kind != "project_pledge":
        amount = normalize_amount(raw_amount)
        if pledge_kind == "stop_gift" and Decimal(amount) > STOP_GIFT_MAX_EUR:
            raise ValueError(f"stop_gift amount must not exceed {STOP_GIFT_MAX_EUR:.2f} EUR")
        exact = _EXACT_PRICE.get(pledge_kind)
        if exact is not None:
            exact *= quantity or 1
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
    if pledge_kind == "cabin_leg":
        from .naviguide_bridge import leg_by_id, leg_milestone_meta, resolve_schedule_milestone

        leg = leg_by_id(resolved_target)
        if leg:
            await resolve_schedule_milestone(leg["id"])
    elif milestone_id:
        from .naviguide_bridge import resolve_schedule_milestone

        await resolve_schedule_milestone(milestone_id)
    if pledge_kind == "project_pledge":
        pledge_currency = "EUR"
        from app.channel3_catalog import catalog_needs_confirmation, lookup_catalog_by_project_id
        from app.channel3_paypal import catalog_project_id, paypal_currency_supported

        catalog = lookup_catalog_by_project_id(
            resolved_target,
            public_only=catalog_project_id(resolved_target),
        )
        if catalog is None:
            pending = lookup_catalog_by_project_id(
                resolved_target,
                include_needs_confirmation=True,
            )
            if pending is not None and catalog_needs_confirmation(pending):
                raise ValueError("catalog item needs confirmation and cannot be funded")
        if catalog_project_id(resolved_target) and catalog is None:
            raise ValueError("catalog item is not available for public funding")
        if catalog:
            from app.channel3_paypal import normalize_project_pledge_amount

            pledge_currency = str(catalog.get("price_currency") or "EUR").upper()
            if not paypal_currency_supported(pledge_currency):
                raise ValueError(
                    f"PayPal checkout does not support catalog currency {pledge_currency}"
                )
            amount = normalize_project_pledge_amount(raw_amount, pledge_currency)
        elif amount is None:
            amount = normalize_amount(raw_amount)
            if Decimal(amount) < Decimal("1.00"):
                raise ValueError("project_pledge amount must be at least 1.00 EUR")
        return await _create_capture_pledge(
            amount=amount,
            description=description,
            milestone_id=milestone_id,
            client=client,
            client_key=client_key,
            contributor=contributor,
            target_id=resolved_target,
            return_url=return_url,
            cancel_url=cancel_url,
            caller_origin=caller_origin,
            checkout_locale=checkout_locale,
            checkout_method=checkout_method,
            currency=pledge_currency,
        )
    mode: PaymentMode = payment_mode or "AUTHORIZE"
    from .departure_clock import refuse_cancelled_departure

    draft = {
        "milestone_id": milestone_id,
        "kind": pledge_kind,
        "target_id": resolved_target,
    }
    await refuse_cancelled_departure(draft)
    # An authorization lasts 29 days. Refuse before PayPal creates the order.
    # When Vault is on, a far departure falls back to saving the payment method.
    from .payment_mode import resolve_pledge_mode
    mode = await resolve_pledge_mode(draft, mode=mode)
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
            checkout_locale=checkout_locale,
            checkout_method=checkout_method,
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
        checkout_locale=checkout_locale,
        checkout_method=checkout_method,
    )


async def _create_capture_pledge(
    *,
    amount: str,
    description: str,
    milestone_id: str,
    client: Any,
    client_key: Optional[str],
    contributor: Optional[str],
    target_id: str,
    return_url: Optional[str] = None,
    cancel_url: Optional[str] = None,
    caller_origin: Optional[str] = None,
    checkout_locale: Optional[str] = None,
    checkout_method: Optional[str] = None,
    currency: str = "EUR",
) -> dict:
    """Project crowdfunding: CAPTURE intent, charged when the buyer approves on return."""
    key = _client_key(client_key)
    ledger = get_ledger()
    if key:
        existing = await ledger.find_by_client_key(key)
        if existing:
            return existing
    pledge_id = uuid.uuid4().hex
    idempotency_key = key or uuid.uuid4().hex
    method = _normalize_checkout_method(checkout_method)
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
    pledge_currency = str(currency or "EUR").strip().upper()
    from app.channel3_paypal import format_paypal_amount_value

    paypal_amount = format_paypal_amount_value(amount, pledge_currency)
    method_options = {"checkout_method": "card"} if method == "card" else {}
    order = await asyncio.to_thread(_create_capture_order,
        client,
        amount_eur=paypal_amount,
        description=description,
        reference_id=pledge_id,
        idempotency_key=idempotency_key,
        return_url=back,
        cancel_url=cancel,
        checkout_locale=checkout_locale,
        currency_code=pledge_currency,
        **method_options,
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
        "intent": "CAPTURE",
        "payment_mode": "CAPTURE",
        "currency": pledge_currency,
        "amount_eur": amount,
        "description": description,
        "milestone_id": milestone_id,
        "kind": "project_pledge",
        "target_id": target_id,
        "contributor": (contributor or "").strip() or None,
        "order_id": order_id,
        "approve_link": approve_link(order),
        "authorization_id": None,
        "authorization_expires_at": None,
        "vault_id": None,
        "vault_source": None,
        "setup_token_id": None,
        "checkout_method": method,
        "vault_on_purchase": False,
        "checkout_locale": (checkout_locale or "").strip() or None,
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
            currency=pledge_currency,
            order_id=order_id,
            status="created",
            payment_mode="CAPTURE",
            **_identity(saved),
        )
    return saved


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
    checkout_locale: Optional[str] = None,
    checkout_method: Optional[str] = None,
) -> dict:
    key = _client_key(client_key)
    ledger = get_ledger()
    if key:
        existing = await ledger.find_by_client_key(key)
        if existing:
            return existing
    pledge_id = uuid.uuid4().hex
    idempotency_key = key or uuid.uuid4().hex
    method = _normalize_checkout_method(checkout_method)
    from .config import card_fields_enabled, vault_on_purchase_enabled

    if method == "card" and not card_fields_enabled():
        raise ValueError("card checkout is disabled")
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
    order_kwargs = dict(
        amount_eur=amount,
        description=description,
        reference_id=pledge_id,
        idempotency_key=idempotency_key,
        return_url=back,
        cancel_url=cancel,
        checkout_locale=checkout_locale,
    )
    platform_fees_on_order = False
    if method == "card":
        order = await asyncio.to_thread(_create_card_authorize_order, client, **order_kwargs)
    elif vault_on_purchase_enabled():
        order = await asyncio.to_thread(_create_authorize_vault_order, client, **order_kwargs)
    else:
        from .config import (
            paypal_berth_platform_fees_on_order,
            platform_fee_eur,
            platform_payee_merchant_id,
            marina_seller_merchant_id,
        )

        if kind == "berth" and paypal_berth_platform_fees_on_order(target_id):
            order = await asyncio.to_thread(client.create_authorize_order,
                **order_kwargs,
                payee_merchant_id=marina_seller_merchant_id(target_id),
                platform_fee_eur=platform_fee_eur(),
                platform_merchant_id=platform_payee_merchant_id(),
            )
            platform_fees_on_order = True
        else:
            order = await asyncio.to_thread(_create_authorize_order, client, **order_kwargs)
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
        "checkout_method": method,
        # Card and vault orders never carry multiparty fees; settlement pays the marina instead.
        "platform_fees_on_order": platform_fees_on_order,
        "vault_on_purchase": vault_on_purchase_enabled() and method != "card",
        "checkout_locale": (checkout_locale or "").strip() or None,
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
    checkout_locale: Optional[str] = None,
    checkout_method: Optional[str] = None,
) -> dict:
    key = _client_key(client_key)
    ledger = get_ledger()
    if key:
        existing = await ledger.find_by_client_key(key)
        if existing:
            return existing
    pledge_id = uuid.uuid4().hex
    idempotency_key = key or uuid.uuid4().hex
    method = _normalize_checkout_method(checkout_method)
    from .config import card_fields_enabled

    if method == "card" and not card_fields_enabled():
        raise ValueError("card checkout is disabled")
    back = _vault_callback_url(vault_return_url(), pledge_id, "return")
    cancel = _vault_callback_url(vault_cancel_url(), pledge_id, "cancel")
    if method == "card":
        setup = await asyncio.to_thread(_create_card_setup_token,
            client,
            return_url=back,
            cancel_url=cancel,
            customer_id=sponsor_customer_id(pledge_id, contributor),
            idempotency_key=idempotency_key,
            checkout_locale=checkout_locale,
        )
    else:
        setup = await asyncio.to_thread(client.create_setup_token,
            back,
            cancel,
            customer_id=sponsor_customer_id(pledge_id, contributor),
            idempotency_key=idempotency_key,
            checkout_locale=checkout_locale,
        )
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
        "checkout_method": method,
        "checkout_locale": (checkout_locale or "").strip() or None,
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


async def admin_reauthorize_pledge(
    pledge_id: str,
    client: Any,
    *,
    mock_response: Optional[str] = None,
    effective_at: Optional[dt.datetime] = None,
) -> dict:
    """TEST-only treasurer helper: force honor-period reauthorize on an AUTHORIZE pledge."""
    if mock_response:
        client.mock_response = mock_response
    pledge = await require_pledge(pledge_id)
    if pledge.get("payment_mode") not in {None, "AUTHORIZE"} and pledge.get("intent") != "AUTHORIZE":
        raise ValueError("reauthorize applies to AUTHORIZE pledges only")
    if pledge.get("status") != "authorized":
        raise ValueError("pledge must be authorized")
    if not pledge.get("authorization_id"):
        raise ValueError("authorization_id missing")
    changed = await asyncio.to_thread(_prepare_authorization_capture, pledge, client, now=effective_at)
    if not changed:
        raise ValueError("authorization is still inside the honor period")
    return await get_ledger().save_pledge(pledge)


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
    shown = await asyncio.to_thread(client.get_setup_token, token_id)
    if str((shown or {}).get("status") or "").upper() != "APPROVED":
        raise ValueError("setup token is not approved")
    payment_token = await asyncio.to_thread(client.create_payment_token, token_id, pledge_id=pledge_id)
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


def _require_status(pledge: dict, expected: str | tuple[str, ...], target: str) -> None:
    current = pledge.get("status")
    allowed = expected if isinstance(expected, tuple) else (expected,)
    if current not in allowed:
        raise IllegalTransition(str(current), target)


def _require_card_capture_approval(order: dict) -> None:
    """Fail closed on unknown/failed 3DS; use PayPal's server response matrix."""
    if str(order.get("status") or "").upper() not in {"APPROVED", "COMPLETED"}:
        raise ValueError("card order not approved yet")
    card = (order.get("payment_source") or {}).get("card") or {}
    auth = card.get("authentication_result") or {}
    # SCA_WHEN_REQUIRED may not request authentication. PayPal then returns an
    # approved card source without authentication_result, not an UNKNOWN result.
    if ("authentication_result" not in card and str(order.get("status") or "").upper() == "APPROVED"
            and card.get("last_digits") and card.get("brand")):
        return
    three_ds = auth.get("three_d_secure") or {}
    enrolled = str(three_ds.get("enrollment_status") or "").upper()
    status = str(three_ds.get("authentication_status") or "").upper()
    liability = str(auth.get("liability_shift") or "").upper()
    authenticated = enrolled == "Y" and status in {"Y", "A"} and liability == "POSSIBLE"
    exempt = enrolled in {"N", "U", "B"} and not status and liability == "NO"
    if not (authenticated or exempt):
        raise ValueError("card authentication incomplete or declined; retry or choose another payment method")


async def _capture_order_pledge(pledge_id: str, client: Any, pledge: dict) -> dict:
    """Capture a CAPTURE-intent order after the buyer approved on PayPal."""
    _require_status(pledge, "created", "captured")
    order_id = str(pledge.get("order_id") or "")
    if pledge.get("checkout_method") == "card":
        getter = getattr(client, "get_card_order", None) or getattr(client, "get_order", None)
        if not callable(getter):
            raise ValueError("card approval cannot be verified")
        _require_card_capture_approval(await asyncio.to_thread(getter, order_id) or {})
    elif not await asyncio.to_thread(_buyer_approved, client, order_id):
        raise ValueError("order not approved yet")
    capture = getattr(client, "capture_order", None)
    if capture is None:
        raise PayPalError(502, "order capture unavailable")
    pledge, payload = await _call_with_capture_idempotency(
        pledge,
        lambda key: capture(order_id, idempotency_key=key),
    )
    return await _finish_capture(
        pledge,
        payload,
        finance={"payment_mode": "CAPTURE", "order_id": order_id},
        client=client,
    )


async def _finish_pledge_authorization(
    pledge: dict,
    order: dict,
    client: Any,
    *,
    auth_id: Optional[str] = None,
    expiration: Optional[str] = None,
) -> dict:
    if not auth_id:
        auth_id, expiration = authorization_from(order)
    if pledge.get("vault_on_purchase"):
        vault_id = vault_id_from_order(order if isinstance(order, dict) else {})
        if not vault_id:
            order_id = str(pledge.get("order_id") or "")
            try:
                refreshed = await asyncio.to_thread(client.get_order, order_id) or {}
            except Exception:
                refreshed = {}
            vault_id = vault_id_from_order(refreshed)
        if vault_id:
            pledge["vault_id"] = vault_id
            pledge["history"] = list(pledge.get("history") or []) + ["vault_id_saved"]
    pledge["status"] = "authorized"
    pledge["authorized_at"] = _money_event_timestamp()
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


async def authorize_pledge(pledge_id: str, client: Any) -> dict:
    pledge = await require_pledge(pledge_id)
    mode = str(pledge.get("payment_mode") or pledge.get("intent") or "AUTHORIZE")
    if mode == "CAPTURE":
        async with _serialize_pledge_authorize(pledge_id):
            pledge = await require_pledge(pledge_id)
            if pledge.get("status") == "pending":
                return await _refresh_pending_capture(pledge, client)
            if pledge.get("status") in {"captured", "settled"}:
                return pledge
            return await _capture_order_pledge(pledge_id, client, pledge)
    async with _serialize_pledge_authorize(pledge_id):
        pledge = await require_pledge(pledge_id)
        if str(pledge.get("status") or "") == "authorized":
            existing = str(pledge.get("authorization_id") or "").strip()
            if existing:
                return pledge
        _require_status(pledge, "created", "authorized")
        order_id = str(pledge.get("order_id") or "")
        if not await asyncio.to_thread(_buyer_approved, client, order_id):
            raise ValueError("order not approved yet")
        from .departure_clock import refuse_cancelled_departure

        await refuse_cancelled_departure(pledge)
        try:
            order = await asyncio.to_thread(client.authorize_order, order_id, pledge_id=pledge_id)
        except PayPalError as exc:
            if not paypal_error_has_issue(exc, "ORDER_ALREADY_AUTHORIZED"):
                raise
            refreshed = await asyncio.to_thread(client.get_order, order_id) or {}
            mismatch = adopted_authorization_mismatch(refreshed, pledge)
            if mismatch:
                log.warning(
                    "ORDER_ALREADY_AUTHORIZED adoption refused pledge_id=%s order_id=%s mismatch=%s",
                    pledge_id,
                    order_id,
                    mismatch,
                )
                raise exc from None
            try:
                auth_id, expiration = usable_authorization_from_order(refreshed)
            except PayPalError:
                raise exc from None
            return await _finish_pledge_authorization(
                pledge,
                refreshed,
                client,
                auth_id=auth_id,
                expiration=expiration,
            )
        return await _finish_pledge_authorization(pledge, order, client)


def _money_event_timestamp(
    at: Optional[dt.datetime] = None,
    *,
    not_before: Optional[str] = None,
) -> str:
    moment = (at or simulated_now()).replace(microsecond=0)
    floor = _parse_moment(not_before)
    if floor is not None and moment < floor:
        moment = floor
    return moment.isoformat()


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
    return moment.astimezone(dt.timezone.utc)


def _prepare_authorization_capture(
    pledge: dict,
    client: Any,
    *,
    now: Optional[dt.datetime] = None,
) -> bool:
    """Reauthorize once the 3-day honor period has passed, and refuse an expired hold."""
    moment = now or simulated_now()
    expires = _parse_moment(pledge.get("authorization_expires_at"))
    if expires is not None and moment >= expires:
        raise ValueError("PayPal authorization has expired")
    authorized_at = _parse_moment(pledge.get("authorized_at"))
    if authorized_at is None or moment <= authorized_at + dt.timedelta(days=HONOR_DAYS):
        return False
    try:
        refreshed = client.reauthorize(
            pledge["authorization_id"],
            pledge_id=str(pledge.get("_id") or ""),
        ) or {}
    except PayPalError:
        if expires is not None and moment >= expires:
            raise ValueError("PayPal authorization has expired") from None
        return False
    new_id = refreshed.get("id") or pledge.get("authorization_id")
    pledge["authorization_id"] = str(new_id)
    expiration = refreshed.get("expiration_time")
    if expiration:
        pledge["authorization_expires_at"] = str(expiration)
    pledge["authorized_at"] = _money_event_timestamp(moment)
    pledge["history"] = list(pledge.get("history") or []) + ["reauthorized"]
    return True


async def _finish_capture(
    pledge: dict,
    payload: Any,
    *,
    finance: dict,
    effective_at: Optional[dt.datetime] = None,
    client: Any = None,
) -> dict:
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
        if not str(pledge.get("captured_at") or "").strip():
            pledge["captured_at"] = _money_event_timestamp(
                effective_at,
                not_before=str(pledge.get("authorized_at") or ""),
            )
        pledge["history"] = list(pledge.get("history") or []) + ["captured"]
        from .paypal_settlement import apply_capture_settlement

        pledge = apply_capture_settlement(
            pledge,
            payload if isinstance(payload, dict) else {},
        )
        saved = await get_ledger().save_pledge(pledge)
        await record("capture", status="captured", **audit_fields)
        return await record_pledge_captured_once(saved, actor="treasurer", client=client)
    if status == "PENDING":
        pledge["status"] = "pending"
        pledge["history"] = list(pledge.get("history") or []) + ["pending"]
        saved = await get_ledger().save_pledge(pledge)
        await record("capture", status="pending", **audit_fields)
        await record_finance("pledge_capture_pending", status="pending", **base)
        return saved

    failed_status = "charge_failed" if mode == "VAULT" else "capture_failed"
    pledge["status"] = failed_status
    pledge["history"] = list(pledge.get("history") or []) + [failed_status]
    saved = await get_ledger().save_pledge(pledge)
    await record(failed_status, status=saved.get("status"), **audit_fields)
    finance_event = "pledge_charge_failed" if mode == "VAULT" else "pledge_capture_failed"
    await record_finance(finance_event, status=saved.get("status"), **base)
    raise ValueError(f"PayPal capture status {recorded} is not COMPLETED or PENDING")


async def mark_vault_charge_failed(pledge_id: str, detail: str) -> dict:
    """Vault charge declined or requires payer action — do not retry on every settle."""
    from .audit import record

    pledge = await require_pledge(pledge_id)
    pledge["status"] = "charge_failed"
    pledge["paypal_status"] = str(detail or "")[:120]
    pledge["history"] = list(pledge.get("history") or []) + ["charge_failed"]
    saved = await get_ledger().save_pledge(pledge)
    await record(
        "charge_failed",
        pledge_id=saved["_id"],
        milestone_id=saved.get("milestone_id"),
        detail=str(detail or "")[:200],
        **_identity(saved),
    )
    await record_finance(
        "pledge_charge_failed",
        pledge_id=saved["_id"],
        milestone_id=saved.get("milestone_id"),
        amount_eur=saved.get("amount_eur"),
        status="charge_failed",
        **_identity(saved),
    )
    return saved


async def mark_vault_token_delete_after_capture(pledge_id: str, detail: str) -> dict:
    """Vault charge succeeded but token delete failed — keep captured, retry delete later."""
    from .audit import record

    pledge = await require_pledge(pledge_id)
    if str(pledge.get("status") or "") != "captured":
        raise ValueError("vault token delete retry applies only to captured pledges")
    pledge["vault_token_delete_pending"] = True
    pledge["vault_delete_detail"] = str(detail or "")[:200]
    pledge["history"] = list(pledge.get("history") or []) + ["vault_token_delete_pending"]
    saved = await get_ledger().save_pledge(pledge)
    await record(
        "vault_token_delete_pending",
        pledge_id=saved["_id"],
        milestone_id=saved.get("milestone_id"),
        detail=str(detail or "")[:200],
        payment_mode="VAULT",
        **_identity(saved),
    )
    return saved


async def retry_vault_token_delete(pledge_id: str, client: Any) -> dict:
    """Retry PayPal vault token delete for a captured pledge."""
    pledge = await require_pledge(pledge_id)
    if not pledge.get("vault_token_delete_pending"):
        return pledge
    vault_id = str(pledge.get("vault_id") or "").strip()
    if not vault_id:
        raise ValueError("vault_id is required to delete token")
    await release_vault_token_if_unused(client, vault_id, exclude_pledge_id=pledge_id)
    pledge = await require_pledge(pledge_id)
    pledge["vault_token_delete_pending"] = False
    pledge.pop("vault_delete_detail", None)
    pledge["history"] = list(pledge.get("history") or []) + ["vault_token_deleted"]
    return await get_ledger().save_pledge(pledge)


async def mark_token_delete_pending(pledge_id: str, detail: str) -> dict:
    """PayPal vault token delete failed on void — retry on the next departure settle."""
    from .audit import record

    pledge = await require_pledge(pledge_id)
    pledge["status"] = "token_delete_pending"
    pledge["paypal_status"] = str(detail or "")[:120]
    pledge["history"] = list(pledge.get("history") or []) + ["token_delete_pending"]
    saved = await get_ledger().save_pledge(pledge)
    await record(
        "token_delete_pending",
        pledge_id=saved["_id"],
        milestone_id=saved.get("milestone_id"),
        detail=str(detail or "")[:200],
        payment_mode="VAULT",
        **_identity(saved),
    )
    return saved


async def _refresh_pending_capture(pledge: dict, client: Any) -> dict:
    """Reconcile the existing capture; PENDING never permits a second charge."""
    capture_id = str(pledge.get("capture_id") or "")
    if not capture_id:
        raise ValueError("pending payment has no capture ID; await PayPal reconciliation")
    payload = await asyncio.to_thread(client.get_capture, capture_id)
    status, returned_id, _ = read_capture_result(payload)
    if returned_id != capture_id:
        raise PayPalError(502, "Pending capture identity mismatch")
    if status == "PENDING":
        return pledge
    if status not in {"COMPLETED", "DECLINED", "FAILED", "DENIED"}:
        raise PayPalError(502, "Pending capture returned an unresolved status")
    await _record_capture_attempt_outcome(pledge, payload)
    return await _finish_capture(
        pledge, payload,
        finance={"payment_mode": pledge.get("payment_mode") or "AUTHORIZE"},
        client=client,
    )


async def capture_pledge(
    pledge_id: str,
    client: Any,
    *,
    effective_at: Optional[dt.datetime] = None,
) -> dict:
    async with _serialize_pledge_authorize(pledge_id):
        return await _capture_pledge_locked(pledge_id, client, effective_at=effective_at)


async def _capture_pledge_locked(
    pledge_id: str,
    client: Any,
    *,
    effective_at: Optional[dt.datetime] = None,
) -> dict:
    pledge = await require_pledge(pledge_id)
    from .departure_clock import refuse_early_capture

    if pledge.get("status") == "pending":
        return await _refresh_pending_capture(pledge, client)

    mode = pledge.get("payment_mode") or pledge.get("intent") or "AUTHORIZE"
    if mode == "VAULT":
        _require_status(pledge, ("vaulted", "charge_failed"), "captured")
        await refuse_early_capture(pledge, now=effective_at)
        vault_id = pledge.get("vault_id")
        if not vault_id:
            raise IllegalTransition("vaulted", "captured")
        pledge, payload = await _call_with_capture_idempotency(
            pledge,
            lambda key: client.charge_vaulted(
                vault_id,
                pledge["amount_eur"],
                pledge_id,
                source=pledge.get("vault_source") or "paypal",
                description=str(pledge.get("description") or ""),
                idempotency_key=key,
            ),
        )
        saved = await _finish_capture(
            pledge,
            payload,
            finance={"vault_id": vault_id, "payment_mode": "VAULT"},
            effective_at=effective_at,
            client=client,
        )
        if saved.get("status") == "captured":
            try:
                await release_vault_token_if_unused(
                    client, str(vault_id), exclude_pledge_id=pledge_id,
                )
                reloaded = await get_ledger().get_pledge(pledge_id)
                if reloaded:
                    saved = reloaded
            except Exception as exc:
                saved = await mark_vault_token_delete_after_capture(
                    pledge_id, _vault_delete_failure_detail(exc),
                )
        return saved
    _require_status(pledge, ("authorized", "capture_failed"), "captured")
    if not pledge.get("authorization_id"):
        raise IllegalTransition("authorized", "captured")
    await refuse_early_capture(pledge, now=effective_at)
    if await asyncio.to_thread(_prepare_authorization_capture, pledge, client):
        pledge = await get_ledger().save_pledge(pledge)
    pledge, payload = await _call_with_capture_idempotency(
        pledge,
        lambda key: client.capture_authorization(
            pledge["authorization_id"],
            idempotency_key=key,
        ),
    )
    return await _finish_capture(
        pledge,
        payload,
        finance={"authorization_id": pledge.get("authorization_id")},
        effective_at=effective_at,
        client=client,
    )


_VAULT_VOID_CLOSED = frozenset({
    "voided",
    "captured",
    "charge_failed",
    "refunded",
    "partially_refunded",
})


def _vault_delete_failure_detail(exc: Exception) -> str:
    if isinstance(exc, PayPalError):
        return str(exc.body or exc)[:200]
    return str(exc)[:200]


async def _other_open_pledges_share_vault(vault_id: str, exclude_pledge_id: str) -> bool:
    """True when another non-terminal pledge still references the same vault token."""
    vid = str(vault_id or "").strip()
    if not vid:
        return False
    for row in await get_ledger().list_pledges():
        if str(row.get("_id") or "") == exclude_pledge_id:
            continue
        if str(row.get("vault_id") or "") != vid:
            continue
        if str(row.get("status") or "") in _VAULT_VOID_CLOSED:
            continue
        return True
    return False


async def find_pledge_by_vault_id(vault_id: str) -> Optional[dict]:
    vid = str(vault_id or "").strip()
    if not vid:
        return None
    for row in await get_ledger().list_pledges():
        if str(row.get("vault_id") or "") == vid:
            return row
    return None


async def mark_vault_token_deleted_for_vault_id(vault_id: str) -> list[str]:
    """Mark every pledge on this vault token deleted (idempotent)."""
    updated: list[str] = []
    vid = str(vault_id or "").strip()
    if not vid:
        return updated
    for row in await get_ledger().list_pledges():
        if str(row.get("vault_id") or "") != vid:
            continue
        pledge_id = str(row.get("_id") or "")
        if row.get("vault_token_deleted") is True:
            if pledge_id:
                updated.append(pledge_id)
            continue
        row["vault_token_deleted"] = True
        row["history"] = list(row.get("history") or []) + ["vault_token_deleted"]
        saved = await get_ledger().save_pledge(row)
        updated.append(str(saved.get("_id") or pledge_id))
    return updated


async def release_vault_token_if_unused(
    client: Any,
    vault_id: str,
    *,
    exclude_pledge_id: str = "",
) -> bool:
    """Delete the PayPal vault token when no open pledge still references it."""
    if await _other_open_pledges_share_vault(vault_id, exclude_pledge_id):
        return False
    vid = str(vault_id or "").strip()
    if not vid:
        return False
    await asyncio.to_thread(client.delete_payment_token, vid)
    await mark_vault_token_deleted_for_vault_id(vid)
    return True


def _finish_vault_void(pledge: dict, *, token_deleted: bool, effective_at: Optional[dt.datetime] = None) -> None:
    """Void a vaulted pledge without storing PayPal authorization void_id fields."""
    pledge.pop("void_id", None)
    pledge.pop("void_id_source", None)
    pledge.pop("void_note", None)
    pledge["vault_token_deleted"] = token_deleted
    pledge["vault_voided_at"] = _money_event_timestamp(
        effective_at,
        not_before=str(pledge.get("captured_at") or pledge.get("authorized_at") or ""),
    )
    pledge["status"] = "voided"
    pledge["history"] = list(pledge.get("history") or []) + ["voided"]


def _stamp_void(
    pledge: dict,
    payload: Any,
    fallback_id: str,
    *,
    hold: str,
    effective_at: Optional[dt.datetime] = None,
) -> None:
    """Store the id PayPal's void returns.

    A void of an authorization is often HTTP 204 with no body, or a body whose
    ``id`` is the authorization itself. When the body has an id, that id is
    ``void_id`` and ``void_id_source`` is ``paypal``. When it does not,
    ``void_id`` is the authorization id (or the vault id) and ``void_note``
    says so.
    """
    body = payload if isinstance(payload, dict) else {}
    returned = str(body.get("id") or "").strip()
    if returned:
        pledge["void_id"] = returned
        pledge["void_id_source"] = "paypal"
        pledge.pop("void_note", None)
    else:
        fallback = str(fallback_id or "").strip()
        if not fallback:
            raise PayPalError(502, "void id missing")
        pledge["void_id"] = fallback
        pledge["void_id_source"] = hold
        pledge["void_note"] = f"PayPal's void returned no id. void_id is the {hold} id."
    pledge["voided_at"] = _money_event_timestamp(
        effective_at,
        not_before=str(pledge.get("authorized_at") or ""),
    )
    pledge["status"] = "voided"
    pledge["history"] = list(pledge.get("history") or []) + ["voided"]


async def void_pledge(
    pledge_id: str,
    client: Any,
    *,
    effective_at: Optional[dt.datetime] = None,
) -> dict:
    pledge = await require_pledge(pledge_id)
    mode = pledge.get("payment_mode") or pledge.get("intent") or "AUTHORIZE"
    if mode == "VAULT":
        _require_status(pledge, ("vaulted", "token_delete_pending"), "voided")
        vault_id = pledge.get("vault_id")
        if not vault_id:
            raise IllegalTransition("vaulted", "voided")
        token_deleted = await release_vault_token_if_unused(
            client,
            str(vault_id),
            exclude_pledge_id=pledge_id,
        )
        _finish_vault_void(pledge, token_deleted=token_deleted, effective_at=effective_at)
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
            vault_token_deleted=saved.get("vault_token_deleted"),
            vault_voided_at=saved.get("vault_voided_at"),
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
            vault_token_deleted=saved.get("vault_token_deleted"),
            vault_voided_at=saved.get("vault_voided_at"),
            **_identity(saved),
        )
        return saved
    _require_status(pledge, "authorized", "voided")
    if not pledge.get("authorization_id"):
        raise IllegalTransition("authorized", "voided")
    released = await asyncio.to_thread(client.void_authorization, pledge["authorization_id"], pledge_id=pledge_id)
    _stamp_void(
        pledge,
        released,
        str(pledge["authorization_id"]),
        hold="authorization",
        effective_at=effective_at,
    )
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


async def refund_pledge(
    pledge_id: str,
    client: Any,
    *,
    amount_eur: Optional[str] = None,
    effective_at: Optional[dt.datetime] = None,
    request_key: Optional[str] = None,
    paypal_refund_id: Optional[str] = None,
) -> dict:
    """Treasurer refund for a captured pledge. Does not run without admin approval."""
    from .audit import record

    pledge = await require_pledge(pledge_id)
    pledge_currency = str(pledge.get("currency") or "EUR").strip().upper()
    from app.channel3_paypal import format_paypal_amount_value, normalize_project_pledge_amount

    current = str(pledge.get("status") or "")
    if current not in ("captured", "partially_refunded", "refunded"):
        raise IllegalTransition(current, "refunded")
    capture_id = str(pledge.get("capture_id") or "").strip()
    if not capture_id:
        raise ValueError("capture_id is required to refund")
    capture_total = Decimal(str(pledge.get("amount_eur") or "0"))
    already_refunded = refunded_amount_from_pledge(pledge)
    remaining = capture_total - already_refunded
    expected_refund_id = str(paypal_refund_id or "").strip()
    pending = pledge.get("pending_refund")
    resuming_pending = isinstance(pending, dict) and str(pending.get("key") or "").strip()
    new_pending_row: Optional[dict] = None
    if resuming_pending:
        idempotency_key = str(pending["key"])
        refund_this = Decimal(str(pending.get("amount") or "0"))
        if refund_this <= Decimal("0"):
            refund_this = remaining
        if not expected_refund_id:
            expected_refund_id = str(pending.get("paypal_refund_id") or "").strip()
    else:
        if amount_eur:
            if pledge_currency == "EUR":
                refund_this = Decimal(normalize_amount(amount_eur))
            else:
                refund_this = Decimal(normalize_project_pledge_amount(amount_eur, pledge_currency))
        else:
            refund_this = remaining
        if refund_this <= Decimal("0"):
            if remaining > Decimal("0"):
                raise ValueError("refund amount must be positive")
        refund_value = format_paypal_amount_value(f"{refund_this}", pledge_currency)
        caller = str(request_key or "").strip()
        if caller:
            idempotency_key = _refund_request_idempotency_key(pledge_id, caller)
        else:
            idempotency_key = _refund_amount_idempotency_key(pledge_id, refund_value)
        new_pending_row = {
            "key": idempotency_key,
            "amount": refund_value,
        }
        if caller:
            new_pending_row["request_key"] = caller
        if expected_refund_id:
            new_pending_row["paypal_refund_id"] = expected_refund_id
    refund_value = format_paypal_amount_value(f"{refund_this}", pledge_currency)
    pledge = await require_pledge(pledge_id)
    already_refunded = refunded_amount_from_pledge(pledge)
    remaining = capture_total - already_refunded
    if expected_refund_id and _refund_row_for_paypal_id(pledge, expected_refund_id):
        return await _finish_idempotent_refund(pledge_id, pledge)
    caller_key = str(request_key or "").strip()
    if resuming_pending and isinstance(pending, dict):
        caller_key = caller_key or str(pending.get("request_key") or "").strip()
    existing_key_row = _refund_row_for_key(pledge, idempotency_key)
    if caller_key:
        if existing_key_row:
            return await _finish_idempotent_refund(pledge_id, pledge)
    elif existing_key_row:
        if resuming_pending:
            return await _finish_idempotent_refund(pledge_id, pledge)
        if refund_this <= remaining:
            raise RefundRequestKeyRequired()
        return await _finish_idempotent_refund(pledge_id, pledge)
    if remaining <= Decimal("0") and already_refunded > Decimal("0"):
        raise PledgeAlreadyFullyRefunded(_ledger_paypal_refund_id(pledge))
    if refund_this > remaining:
        raise ValueError("refund exceeds remaining refundable amount")
    if not resuming_pending and new_pending_row is not None:
        pledge["pending_refund"] = new_pending_row
        pledge = await get_ledger().save_pledge(pledge)
    try:
        payload = await asyncio.to_thread(client.refund_capture,
            capture_id,
            amount_eur=refund_value,
            currency_code=pledge_currency,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        if _is_transport_retry(exc):
            raise
        raise
    if not isinstance(payload, dict):
        raise ValueError("PayPal refund response is invalid")
    refund_id = str(payload.get("id") or "").strip()
    refund_status = str(payload.get("status") or "").upper()
    if not refund_id:
        raise ValueError("PayPal refund id is required")
    if refund_status not in {"COMPLETED", "PENDING"}:
        raise ValueError(f"PayPal refund status {refund_status or 'MISSING'} is not COMPLETED or PENDING")
    normalized_status = refund_status
    if normalized_status == "REFUNDED":
        normalized_status = "COMPLETED"
    saved = await reconcile_refund_on_pledge(
        pledge,
        refund_id=refund_id,
        amount_eur=refund_value,
        status=normalized_status,
        key=idempotency_key,
        at=_money_event_timestamp(
            effective_at,
            not_before=str(pledge.get("captured_at") or ""),
        ),
        refund_payload=payload,
    )
    saved["refunded_at"] = _money_event_timestamp(
        effective_at,
        not_before=str(pledge.get("captured_at") or ""),
    )
    saved["paypal_status"] = refund_status
    event = "refunded" if saved.get("status") == "refunded" else "partially_refunded"
    saved["history"] = list(saved.get("history") or []) + [event]
    saved = await get_ledger().save_pledge(saved)
    milestone_id = finance_milestone_id(saved)
    await record(
        "refund",
        actor="treasurer",
        pledge_id=saved["_id"],
        milestone_id=milestone_id,
        amount_eur=refund_value,
        currency=pledge_currency,
        capture_id=capture_id,
        refund_id=saved.get("refund_id"),
        refunded_amount_eur=saved.get("refunded_amount_eur"),
        **_identity(saved),
    )
    refund_finance: dict = {}
    refunds = _normalize_refunds(saved)
    if refunds:
        last = refunds[-1]
        if last.get("refund_net_eur") is not None:
            refund_finance["refund_net_eur"] = last.get("refund_net_eur")
    if saved.get("received_net_eur") is not None:
        refund_finance["received_net_eur"] = saved.get("received_net_eur")
    await record_finance(
        "pledge_refunded",
        pledge_id=saved["_id"],
        milestone_id=milestone_id,
        amount_eur=refund_value,
        currency=pledge_currency,
        capture_id=capture_id,
        refund_id=saved.get("refund_id"),
        refunded_amount_eur=saved.get("refunded_amount_eur"),
        status=saved.get("status"),
        actor="treasurer",
        **_identity(saved),
        **refund_finance,
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
