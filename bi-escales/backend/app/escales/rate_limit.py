"""Per-IP limit for the captain routes. In memory, and off outside production.

The chat and review routes share one bucket. Other routes are not counted.
A full UTC day is reported before the sliding minute, and a rejected call
is not stored.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from dataclasses import dataclass
from typing import Optional

from .captain import message_lang
from .config import limits_enabled

logger = logging.getLogger(__name__)

PER_MINUTE_DEFAULT = 10
PER_DAY_DEFAULT = 100
DEMO_PER_MINUTE_DEFAULT = 6
PER_MINUTE_JUDGING_DEFAULT = 36
PER_DAY_JUDGING_DEFAULT = 9000
LLM_DAILY_CAP_JUDGING_DEFAULT = 9000
_MINUTE = dt.timedelta(seconds=60)

_hits: dict[str, list[dt.datetime]] = {}
_demo_hits: dict[str, list[dt.datetime]] = {}


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


def _positive_judging(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s invalid; using judging default %s", name, default)
        return default
    if value <= 0:
        logger.warning("%s invalid; using judging default %s", name, default)
        return default
    return value


def _configured_per_minute() -> int:
    return _positive("ESCALES_CAPTAIN_RATE_PER_MINUTE", PER_MINUTE_DEFAULT)


def _configured_per_day() -> int:
    return _positive("ESCALES_CAPTAIN_RATE_PER_DAY", PER_DAY_DEFAULT)


def _configured_per_minute_judging() -> int:
    return _positive_judging(
        "ESCALES_CAPTAIN_RATE_PER_MINUTE_JUDGING", PER_MINUTE_JUDGING_DEFAULT
    )


def _configured_per_day_judging() -> int:
    return _positive_judging(
        "ESCALES_CAPTAIN_RATE_PER_DAY_JUDGING", PER_DAY_JUDGING_DEFAULT
    )


def llm_daily_cap_judging() -> int:
    return _positive_judging(
        "ESCALES_LLM_DAILY_CAP_JUDGING", LLM_DAILY_CAP_JUDGING_DEFAULT
    )


_JUDGING_CACHE_TTL = dt.timedelta(seconds=60)
_judging_cache: Optional[tuple[dt.datetime, "_JudgingLimits"]] = None
_judging_warning_logged = False


@dataclass(frozen=True)
class _JudgingLimits:
    per_minute: int
    per_day: int
    judging_window_active: bool


def _wall_now() -> dt.datetime:
    """Real UTC wall clock (not ESCALES_CLOCK_NOW / simulated voyage)."""
    return dt.datetime.now(dt.timezone.utc)


def _parse_iso8601_instant(raw: str) -> Optional[dt.datetime]:
    text = (raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _warn_judging_config_once(message: str) -> None:
    global _judging_warning_logged
    if _judging_warning_logged:
        return
    _judging_warning_logged = True
    logger.warning(message)


def _judging_limits_for(now: dt.datetime) -> _JudgingLimits:
    start_raw = (os.environ.get("ESCALES_JUDGING_START") or "").strip()
    end_raw = (os.environ.get("ESCALES_JUDGING_END") or "").strip()
    if not start_raw or not end_raw:
        return _JudgingLimits(
            _configured_per_minute(),
            _configured_per_day(),
            judging_window_active=False,
        )
    start = _parse_iso8601_instant(start_raw)
    end = _parse_iso8601_instant(end_raw)
    if start is None or end is None or start >= end:
        _warn_judging_config_once(
            "ESCALES_JUDGING_START/END invalid or START>=END; judging window disabled"
        )
        return _JudgingLimits(
            _configured_per_minute(),
            _configured_per_day(),
            judging_window_active=False,
        )
    if start <= now < end:
        return _JudgingLimits(
            _configured_per_minute_judging(),
            _configured_per_day_judging(),
            judging_window_active=True,
        )
    return _JudgingLimits(
        _configured_per_minute(),
        _configured_per_day(),
        judging_window_active=False,
    )


def _effective_limits() -> _JudgingLimits:
    global _judging_cache
    now = _wall_now()
    if _judging_cache is not None:
        cached_at, state = _judging_cache
        if now - cached_at < _JUDGING_CACHE_TTL:
            return state
    state = _judging_limits_for(now)
    _judging_cache = (now, state)
    return state


def per_minute() -> int:
    return _effective_limits().per_minute


def per_day() -> int:
    return _effective_limits().per_day


def judging_window_active() -> bool:
    return _effective_limits().judging_window_active


def captain_rate_feature() -> dict[str, int | bool]:
    limits = _effective_limits()
    return {
        "per_minute": limits.per_minute,
        "per_day": limits.per_day,
        "judging_window_active": limits.judging_window_active,
    }


def reset_judging_cache() -> None:
    global _judging_cache, _judging_warning_logged
    _judging_cache = None
    _judging_warning_logged = False


def reset() -> None:
    _hits.clear()
    _demo_hits.clear()
    reset_judging_cache()


def demo_per_minute() -> int:
    return _positive("ESCALES_DEMO_RATE_PER_MINUTE", DEMO_PER_MINUTE_DEFAULT)


def demo_retry_after(ip: str, now: Optional[dt.datetime] = None) -> int:
    """Seconds until this client IP's oldest hit in the sliding minute expires."""
    moment = now or _now()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    else:
        moment = moment.astimezone(dt.timezone.utc)
    key = (ip or "").strip() or "unknown"
    recent = [
        stamp for stamp in _demo_hits.get(key, [])
        if moment - stamp < _MINUTE
    ]
    if not recent:
        return 60
    oldest = min(recent)
    remaining = _MINUTE - (moment - oldest)
    return max(1, int(remaining.total_seconds()) + 1)


class RateLimited(Exception):
    def __init__(self, kind: str, limit: int, *, retry_after: int = 60) -> None:
        self.kind = kind
        self.limit = limit
        self.retry_after = max(1, int(retry_after))
        super().__init__(kind)


def client_ip(forwarded_for: str, host: str, trusted_hops: Optional[int] = None) -> str:
    """Client IP behind trusted proxies (e.g. Render).

    Uses ``parts[-trusted_hops]``: the leftmost ``X-Forwarded-For`` entries are
    caller-controlled and spoofable; the edge proxy appends the real peer on the
    right. ``ESCALES_TRUSTED_PROXY_HOPS`` (default 1) counts in from that edge;
    raise it when another trusted hop is chained. When zero, ignore XFF and use
    ``request.client.host``.
    """
    hops = trusted_proxy_hops() if trusted_hops is None else max(0, int(trusted_hops))
    parts = [part.strip() for part in (forwarded_for or "").split(",") if part.strip()]
    if hops == 0 or not parts:
        return (host or "").strip() or "unknown"
    if len(parts) >= hops:
        return parts[-hops]
    return (host or "").strip() or "unknown"


def _retry_after_day(moment: dt.datetime) -> int:
    next_day = dt.datetime.combine(
        moment.date() + dt.timedelta(days=1),
        dt.time.min,
        tzinfo=dt.timezone.utc,
    )
    return max(1, int((next_day - moment).total_seconds()))


def trusted_proxy_hops() -> int:
    raw = (os.environ.get("ESCALES_TRUSTED_PROXY_HOPS") or "1").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 1


def captain_rate_key(ip: str, session_id: str = "") -> str:
    """``{ip}`` or ``{ip}|{session}`` when the browser sends ``X-Escales-Session``.

    ``hit`` always charges the per-IP bucket; the session bucket only adds a second,
    tighter-or-equal check on top. A rotating session header never gets a fresh quota.
    """
    base = (ip or "").strip() or "unknown"
    session = (session_id or "").strip()[:128]
    if session:
        return f"{base}|{session}"
    return base


def _bucket_keys(key: str) -> list[str]:
    raw = (key or "").strip() or "unknown"
    ip, sep, session = raw.partition("|")
    ip = ip.strip() or "unknown"
    keys = [ip]
    if sep and session.strip():
        keys.append(f"{ip}|{session.strip()}")
    return keys


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
            return (
                f"Too many requests. Try again later. "
                f"The captain accepts {limit} per minute."
            )
        return (
            f"Too many requests. Try again later. "
            f"The captain accepts {limit} per day."
        )
    if kind == "minute":
        return (
            f"Trop de requêtes. Réessayez plus tard. "
            f"Le capitaine accepte {limit} par minute."
        )
    return (
        f"Trop de requêtes. Réessayez plus tard. "
        f"Le capitaine accepte {limit} par jour."
    )


def hit(ip: str, now: Optional[dt.datetime] = None) -> None:
    """Count one captain call. No-op when limits are off (development, tests).

    ``ip`` may be a bare client IP or ``{ip}|{session}`` when ``X-Escales-Session`` is sent.
    """
    if not limits_enabled():
        return
    moment = now or _now()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    else:
        moment = moment.astimezone(dt.timezone.utc)
    buckets: dict[str, list[dt.datetime]] = {}
    for key in _bucket_keys(ip):
        buckets[key] = [
            stamp for stamp in _hits.get(key, [])
            if stamp.date() == moment.date() and stamp <= moment
        ]
    # Check every bucket before storing anything: a rejected call is not counted.
    for key, today in buckets.items():
        recent = [stamp for stamp in today if moment - stamp < _MINUTE]
        if len(today) >= per_day():
            _hits.update(buckets)
            raise RateLimited("day", per_day(), retry_after=_retry_after_day(moment))
        if len(recent) >= per_minute():
            _hits.update(buckets)
            oldest = min(recent)
            pause = max(1, int((_MINUTE - (moment - oldest)).total_seconds()) + 1)
            raise RateLimited("minute", per_minute(), retry_after=pause)
    for key, today in buckets.items():
        today.append(moment)
        _hits[key] = today


def hit_demo(ip: str, now: Optional[dt.datetime] = None) -> None:
    """Judge demo routes: always limited per client IP (sandbox demo treasurer)."""
    moment = now or _now()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    else:
        moment = moment.astimezone(dt.timezone.utc)
    key = (ip or "").strip() or "unknown"
    recent = [
        stamp for stamp in _demo_hits.get(key, [])
        if moment - stamp < _MINUTE
    ]
    limit = demo_per_minute()
    if len(recent) >= limit:
        _demo_hits[key] = recent
        oldest = min(recent)
        pause = max(1, int((_MINUTE - (moment - oldest)).total_seconds()) + 1)
        raise RateLimited("minute", limit, retry_after=pause)
    recent.append(moment)
    _demo_hits[key] = recent
