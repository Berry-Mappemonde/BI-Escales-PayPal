"""Relative schedule instants for NAVIGUIDE tests (departure 2026-11-12)."""
from __future__ import annotations

import datetime as dt

_DEPARTURE = dt.datetime(2026, 11, 12, 8, 0, tzinfo=dt.timezone.utc)


def iso_after_days(days: float, *, hour: int = 8, minute: int = 0, second: int = 0) -> str:
    moment = _DEPARTURE + dt.timedelta(days=days)
    moment = moment.replace(hour=hour, minute=minute, second=second, microsecond=0)
    return moment.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
