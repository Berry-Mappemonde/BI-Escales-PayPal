"""Read-only bridge: NAVIGUIDE escale export → BI milestone rows.

When ``ESCALES_NAVIGUIDE_ENABLED`` is off, ``local_schedule_export`` is used
(no HTTP, no partner). The bridge never writes to NAVIGUIDE.

The local rows are the stopovers of ``frontend/public/route.geojson``,
with the same ids as ``milestoneIdFromName`` and the hour offsets of
``voyageClock.js`` at ``2026-11-12T08:00:00.000Z`` (``route_schedule.json``).
``clock_start()`` shifts those offsets, so the dates follow the 12 November
2026 clock instead of a fixed August/September pair.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any, Optional

import httpx

from ..escales_names import display_name
from .config import clock_start, naviguide_api_base, naviguide_bridge_enabled, naviguide_json_path

_ROUTE_SCHEDULE_PATH = Path(__file__).with_name("route_schedule.json")
# Same civil time as voyageClock.DEFAULT_T0_ISO (08:00Z on the clock date).
_CLOCK_AT = dt.time(8, 0, tzinfo=dt.timezone.utc)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_FOLD = str.maketrans("àâäáéèêëíìîïóòôöúùûüçñ", "aaaaeeeeiiiioooouuuucn")


def _slug(name: str) -> str:
    folded = (name or "").strip().lower().translate(_FOLD)
    return _SLUG_RE.sub("-", folded).strip("-") or "escale"

def _route_stops() -> list[dict[str, Any]]:
    payload = json.loads(_ROUTE_SCHEDULE_PATH.read_text(encoding="utf-8"))
    rows = payload.get("escales") or []
    return [row for row in rows if isinstance(row, dict)]


def _arrival_iso(t_hours: Any) -> str:
    """Arrival on the voyage clock. ``t_hours`` is the offset from 08:00Z."""
    try:
        hours = float(t_hours or 0)
    except (TypeError, ValueError):
        hours = 0.0
    base = dt.datetime.combine(dt.date.fromisoformat(clock_start()), _CLOCK_AT)
    moment = base + dt.timedelta(hours=hours)
    return moment.replace(microsecond=0).isoformat()


def local_schedule_export() -> dict[str, Any]:
    """Fallback schedule when the NAVIGUIDE bridge is disabled.

    Ids and order come from the route. Dates are ``clock_start()`` plus the
    clock offset, so a 12 November 2026 departure keeps Fort-de-France before
    Mayotte and both after that day.
    """
    escales: list[dict[str, Any]] = []
    for item in _route_stops():
        milestone_id = str(item.get("milestone_id") or "").strip()
        if not milestone_id:
            continue
        escales.append(
            {
                "milestone_id": milestone_id,
                "name": item.get("name") or milestone_id,
                "slug": item.get("slug") or milestone_id.removeprefix("dep-"),
                "lat": item.get("lat"),
                "lon": item.get("lon"),
                "arrival_iso": _arrival_iso(item.get("t_hours")),
                "flag": True,
            }
        )
    return {
        "version": 1,
        "provider": "local",
        "clock_start": clock_start(),
        "escales": escales,
    }


def escales_to_milestones(export: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn an export payload into milestone-shaped dicts (no ledger write)."""
    rows: list[dict[str, Any]] = []
    for item in export.get("escales") or []:
        if not isinstance(item, dict):
            continue
        milestone_id = str(item.get("milestone_id") or "").strip()
        named = str(item.get("name") or "").strip()
        if not milestone_id:
            if not named:
                continue
            milestone_id = f"dep-{_slug(named)}"
        shown = named or display_name(str(item.get("slug") or milestone_id))
        rows.append(
            {
                "_id": milestone_id,
                "title": item.get("name") or shown,
                "display_name": shown,
                "arrival_iso": item.get("arrival_iso"),
                "lat": item.get("lat"),
                "lon": item.get("lon"),
                "slug": item.get("slug"),
                "source": export.get("provider") or "NAVIGUIDE",
            }
        )
    return rows


def parse_export(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("export must be a JSON object")
    if "escales" not in raw:
        raise ValueError("export missing escales")
    return raw


def load_export_from_path(path: str) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    return parse_export(json.loads(text))


async def fetch_naviguide_export(client: Optional[httpx.AsyncClient] = None) -> dict[str, Any]:
    """Load escales from a JSON file or NAVIGUIDE ``/escales/export``."""
    if not naviguide_bridge_enabled():
        return local_schedule_export()
    json_path = naviguide_json_path()
    if json_path:
        return load_export_from_path(json_path)
    url = f"{naviguide_api_base()}/escales/export"
    own = client is None
    http = client or httpx.AsyncClient()
    try:
        response = await http.get(url, timeout=15.0)
        response.raise_for_status()
        return parse_export(response.json())
    except Exception:
        return local_schedule_export()
    finally:
        if own:
            await http.aclose()


async def sync_milestone_shells(export: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """Ensure milestone documents exist for each exported escale (meta only)."""
    from .pledges import get_ledger

    payload = export if export is not None else await fetch_naviguide_export()
    rows = escales_to_milestones(payload)
    ledger = get_ledger()
    synced: list[dict[str, Any]] = []
    for row in rows:
        doc = await ledger.ensure_milestone(
            row["_id"],
            meta={
                "title": row.get("title"),
                "display_name": row.get("display_name"),
                "arrival_iso": row.get("arrival_iso"),
                "lat": row.get("lat"),
                "lon": row.get("lon"),
                "source": row.get("source"),
            },
        )
        synced.append(doc)
    return synced
