"""Per-IP limit for the captain routes. In memory, and off outside production.

The chat and review routes share one bucket. Other routes are not counted.
A full UTC day is reported before the sliding minute, and a rejected call
is not stored.
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Optional

from .captain import message_lang
from .config import limits_enabled

PER_MINUTE_DEFAULT = 10
PER_DAY_DEFAULT = 100
_MINUTE = dt.timedelta(seconds=60)

_hits: dict[str, list[dt.datetime]] = {}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _positive(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def per_minute() -> int:
    return _positive("ESCALES_CAPTAIN_RATE_PER_MINUTE", PER_MINUTE_DEFAULT)


def per_day() -> int:
    return _positive("ESCALES_CAPTAIN_RATE_PER_DAY", PER_DAY_DEFAULT)


def reset() -> None:
    _hits.clear()


class RateLimited(Exception):
    def __init__(self, kind: str, limit: int) -> None:
        self.kind = kind
        self.limit = limit
        super().__init__(kind)


def client_ip(forwarded_for: str, host: str) -> str:
    first = (forwarded_for or "").split(",")[0].strip()
    if first:
        return first
    return (host or "").strip() or "unknown"


def lang_for(accept_language: str, text: str = "") -> str:
    """Chat follows the message. A review follows Accept-Language, else French."""
    if (text or "").strip():
        return message_lang(text)
    token = (accept_language or "").split(",")[0].split(";")[0].strip().lower()
    if token.startswith("en"):
        return "en"
    return "fr"


def limit_message(kind: str, lang: str, limit: int) -> str:
    if lang == "en":
        if kind == "minute":
            return f"Too many requests. The captain accepts {limit} per minute."
        return f"Too many requests. The captain accepts {limit} per day."
    if kind == "minute":
        return f"Trop de requêtes. Le capitaine accepte {limit} par minute."
    return f"Trop de requêtes. Le capitaine accepte {limit} par jour."


def hit(ip: str, now: Optional[dt.datetime] = None) -> None:
    """Count one captain call. No-op when limits are off (development, tests)."""
    if not limits_enabled():
        return
    moment = now or _now()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    else:
        moment = moment.astimezone(dt.timezone.utc)
    key = (ip or "").strip() or "unknown"
    today = [
        stamp for stamp in _hits.get(key, [])
        if stamp.date() == moment.date() and stamp <= moment
    ]
    recent = [stamp for stamp in today if moment - stamp < _MINUTE]
    if len(today) >= per_day():
        _hits[key] = today
        raise RateLimited("day", per_day())
    if len(recent) >= per_minute():
        _hits[key] = today
        raise RateLimited("minute", per_minute())
    today.append(moment)
    _hits[key] = today
