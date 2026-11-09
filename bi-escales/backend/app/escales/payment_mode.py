"""Choose AUTHORIZE vs VAULT from milestone horizon and ESCALES_VAULT_ENABLED."""
from __future__ import annotations

import datetime as dt
from typing import Literal, Optional

from .config import AUTH_MAX_DAYS

PaymentMode = Literal["AUTHORIZE", "VAULT", "CAPTURE"]


def _parse_arrival(raw: Optional[str]) -> Optional[dt.datetime]:
    text = (raw or "").strip()
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


def days_until_arrival(arrival_iso: Optional[str], *, now: Optional[dt.datetime] = None) -> Optional[int]:
    """Whole days from ``now`` (UTC) until ``arrival_iso``. None if date is unknown."""
    arrival = _parse_arrival(arrival_iso)
    if arrival is None:
        return None
    moment = now or dt.datetime.now(dt.timezone.utc)
    delta = arrival - moment
    return max(0, delta.days)


def select_payment_mode(
    arrival_iso: Optional[str],
    *,
    now: Optional[dt.datetime] = None,
) -> PaymentMode:
    """Default is AUTHORIZE. VAULT is chosen only in ``create_pledge`` when authorization is too early before departure."""
    _ = (arrival_iso, now)
    return "AUTHORIZE"


async def resolve_pledge_mode(
    draft: dict, *, mode: PaymentMode = "AUTHORIZE", read_only: bool = False,
) -> PaymentMode:
    """Use the same clock, timing anchor and Vault flag for preview and creation."""
    from .config import vault_enabled
    from .departure_clock import refuse_early_authorization

    if mode == "VAULT":
        return mode
    try:
        if read_only:
            await refuse_early_authorization(draft, read_only=True)
        else:
            await refuse_early_authorization(draft)
    except ValueError as exc:
        if vault_enabled() and "29 days" in str(exc):
            return "VAULT"
        raise
    return mode


async def preview_payment_mode(milestone_id: str, kind: str = "mile") -> PaymentMode:
    """Read-only preview: same resolution as ``GET /api/escales/pledges/mode``."""
    from .ledger import get_ledger
    from .naviguide_bridge import leg_departing_from, resolve_milestone
    from .pledges import _kind, _resolve_target

    milestone_id = milestone_id.strip()
    pledge_kind = _kind(kind)
    if pledge_kind == "project_pledge":
        raise ValueError("project_pledge uses PayPal wallet checkout only")
    canonical = (
        "" if pledge_kind == "common_fund" and not milestone_id
        else resolve_milestone(milestone_id)
    )
    if canonical is None:
        if not await get_ledger().get_milestone(milestone_id):
            raise ValueError("milestone_id must name a known stopover")
        canonical = milestone_id
    if pledge_kind == "cabin_leg" and not str(canonical).startswith("leg-"):
        leg = leg_departing_from(canonical)
        if leg:
            canonical = str(leg["id"])
    await _resolve_target(None, canonical, pledge_kind)
    return await resolve_pledge_mode(
        {"milestone_id": canonical, "kind": pledge_kind},
        read_only=True,
    )
