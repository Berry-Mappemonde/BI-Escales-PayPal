"""Read-only navigation logbook per stopover (voyage clock only).

Adapted from naviguide-escales/server/voyage_journal.py (_stop_entry, position
slots) without GRIB, weather, MPA, EEZ, or routing engines.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from .naviguide_bridge import local_schedule_export


def _parse_iso(value: str) -> Optional[dt.datetime]:
    text = (value or "").strip()
    if not text:
        return None
    try:
        moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.astimezone(dt.timezone.utc)


def _lerp(a: float, b: float, ratio: float) -> float:
    r = max(0.0, min(1.0, float(ratio)))
    return a + (b - a) * r


def _position_entry(when: dt.datetime, lat: float, lon: float, name: str) -> dict[str, Any]:
    return {
        "t": when.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "pos": {"lat": round(lat, 4), "lon": round(lon, 4)},
        "label_fr": f"Position — en route vers {name}",
        "label_en": f"Position — underway for {name}",
        "kind": "position",
    }


def _stop_arrival_entry(when: dt.datetime, lat: float, lon: float, name: str) -> dict[str, Any]:
    return {
        "t": when.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "pos": {"lat": round(lat, 4), "lon": round(lon, 4)},
        "label_fr": f"Escale — arrivée {name}",
        "label_en": f"Stopover — arrival at {name}",
        "kind": "stop",
    }


def navigation_logbook(export: Optional[dict[str, Any]] = None) -> dict[str, list[dict[str, Any]]]:
    """A few clock-based entries per stop proving navigation before capture."""
    payload = export if isinstance(export, dict) else local_schedule_export()
    rows = [
        row
        for row in (payload.get("escales") or [])
        if isinstance(row, dict) and row.get("milestone_id") and row.get("arrival_iso")
    ]
    rows.sort(key=lambda row: str(row.get("arrival_iso") or ""))

    by_id: dict[str, list[dict[str, Any]]] = {}
    prev: Optional[dict[str, Any]] = None
    for row in rows:
        milestone_id = str(row.get("milestone_id") or "")
        name = str(row.get("name") or milestone_id)
        arrival = _parse_iso(str(row.get("arrival_iso") or ""))
        lat = float(row.get("lat") or 0)
        lon = float(row.get("lon") or 0)
        if not arrival:
            prev = row
            continue

        entries: list[dict[str, Any]] = []
        if prev and prev.get("arrival_iso"):
            prev_arrival = _parse_iso(str(prev.get("arrival_iso") or ""))
            prev_lat = float(prev.get("lat") or lat)
            prev_lon = float(prev.get("lon") or lon)
            if prev_arrival and prev_arrival < arrival:
                leg = arrival - prev_arrival
                for hours_before, ratio in ((48, 0.55), (12, 0.88)):
                    moment = arrival - dt.timedelta(hours=hours_before)
                    if moment <= prev_arrival:
                        continue
                    entries.append(
                        _position_entry(
                            moment,
                            _lerp(prev_lat, lat, ratio),
                            _lerp(prev_lon, lon, ratio),
                            name,
                        )
                    )
        entries.append(_stop_arrival_entry(arrival, lat, lon, name))
        by_id[milestone_id] = entries[-3:]
        prev = row
    return by_id
