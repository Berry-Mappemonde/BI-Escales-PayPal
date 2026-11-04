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
