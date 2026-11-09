"""Computed voyage-clock instants for tests (no hard-coded 2027 literals).

Anchors: ``cabin_legs.json`` / ``route_schedule.json`` with departure 2026-11-12.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from app.escales.config import PRODUCTION_CLOCK_START, parse_clock_moment
from app.escales.naviguide_bridge import cabin_leg_table, leg_departing_from, local_schedule_export

_DEPARTURE = parse_clock_moment(f"{PRODUCTION_CLOCK_START}T08:00:00Z")


def iso_z(moment: dt.datetime) -> str:
    """UTC ISO with ``Z`` (no microseconds)."""
    normalized = moment.astimezone(dt.timezone.utc).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")


def departure_instant() -> dt.datetime:
    return _DEPARTURE


def departure_plus_days(days: float, *, hour: int = 8) -> str:
    moment = _DEPARTURE + dt.timedelta(days=days)
    moment = moment.replace(hour=hour, minute=0, second=0, microsecond=0, tzinfo=dt.timezone.utc)
    return iso_z(moment)


def _parse_iso(text: str) -> dt.datetime:
    return parse_clock_moment(text)


def _mayotte_arrival_iso() -> str:
    for row in local_schedule_export().get("escales") or []:
        mid = str(row.get("milestone_id") or "")
        if mid in {"dep-mayotte", "dep-dzaoudzi-mayotte"}:
            arrival = row.get("arrival_iso")
            if arrival:
                return str(arrival)
    raise RuntimeError("Mayotte stop missing from local schedule export")


def mayotte_arrival_iso() -> str:
    return _mayotte_arrival_iso()


def near_mayotte_clock() -> str:
    """Mayotte schedule arrival + 16 h (post-arrival capture window)."""
    arrival = _parse_iso(_mayotte_arrival_iso())
    return iso_z(arrival + dt.timedelta(hours=16))


def mayotte_authorize_window_clock() -> str:
    """Ten days before Mayotte arrival, 08:00 UTC (inside the 29-day authorize window)."""
    arrival = _parse_iso(_mayotte_arrival_iso())
    moment = arrival - dt.timedelta(days=10)
    moment = moment.replace(hour=8, minute=0, second=0, microsecond=0)
    return iso_z(moment)


def mayotte_cabin_vault_clock() -> str:
    """Forty days before the cabin leg that departs Mayotte (vault horizon for cabin pledges)."""
    leg = leg_departing_from("dep-dzaoudzi-mayotte")
    if not leg:
        leg = leg_departing_from("dep-mayotte")
    if not leg:
        raise RuntimeError("No cabin leg departing from Mayotte")
    raw = str(leg.get("departure_iso") or "").strip()
    if not raw:
        raise RuntimeError("Mayotte cabin leg has no departure_iso")
    departure = _parse_iso(raw)
    return iso_z(departure - dt.timedelta(days=40))


def synthetic_far_vault_departure_iso() -> str:
    """Fictional long-haul milestone: departure + 60 days."""
    return departure_plus_days(60)


def synthetic_far_vault_capture_clock() -> str:
    """Day after the synthetic far vault departure."""
    dep = _parse_iso(synthetic_far_vault_departure_iso())
    return iso_z(dep + dt.timedelta(days=1))


def cabin_leg_departure_iso(leg_id: str) -> Optional[str]:
    for item in cabin_leg_table().get("legs") or []:
        if str(item.get("id") or "") == leg_id:
            raw = item.get("departure_iso")
            return str(raw) if raw else None
    return None
