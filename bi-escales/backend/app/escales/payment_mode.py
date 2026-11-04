"""Choose AUTHORIZE vs VAULT from milestone horizon and ESCALES_VAULT_ENABLED."""
from __future__ import annotations

import datetime as dt
from typing import Literal, Optional

from .config import AUTH_MAX_DAYS, vault_enabled

PaymentMode = Literal["AUTHORIZE", "VAULT"]


class PaymentDeferred(ValueError):
    """AUTHORIZE cannot cover this milestone. The caller should not create a pledge."""


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
    """AUTHORIZE under 29 days. Farther milestones use VAULT, or they are refused.

    A missing arrival date is refused as well: it used to fall through to
    AUTHORIZE, whose hold expires long before a May 2027 stopover.
    """
    days = days_until_arrival(arrival_iso, now=now)
    if days is None:
        raise PaymentDeferred("a valid milestone arrival date is required")
    if days >= AUTH_MAX_DAYS:
        if not vault_enabled():
            raise PaymentDeferred(
                "milestone is outside the 29-day authorization window; "
                "enable ESCALES_VAULT_ENABLED to save a payment method instead"
            )
        return "VAULT"
    return "AUTHORIZE"
