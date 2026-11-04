"""PayPal Transaction Search windows: real UTC bounds, max 31 days."""

from __future__ import annotations

import datetime as dt

from .config import parse_clock_moment

MAX_TRANSACTION_SEARCH_DAYS = 31


def real_utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_bound(raw: str, *, fallback: dt.datetime) -> dt.datetime:
    text = (raw or "").strip()
    if not text:
        return fallback.replace(microsecond=0)
    return parse_clock_moment(text).replace(microsecond=0)


def clamp_transaction_search_range(
    start_date: str,
    end_date: str,
    *,
    now: dt.datetime | None = None,
) -> tuple[str, str]:
    """Clamp search bounds to real UTC now and PayPal's 31-day window."""
    wall = (now or real_utc_now()).replace(microsecond=0)
    end = _parse_bound(end_date, fallback=wall)
    if end > wall:
        end = wall
    start = _parse_bound(start_date, fallback=end - dt.timedelta(days=7))
    if start > end:
        start = end - dt.timedelta(days=7)
    max_span = dt.timedelta(days=MAX_TRANSACTION_SEARCH_DAYS)
    if end - start > max_span:
        start = end - max_span
    return start.isoformat(), end.isoformat()


def default_transaction_search_window(
    *,
    now: dt.datetime | None = None,
    span_days: int = 7,
) -> tuple[str, str]:
    wall = (now or real_utc_now()).replace(microsecond=0)
    start = wall - dt.timedelta(days=span_days)
    return start.isoformat(), wall.isoformat()
