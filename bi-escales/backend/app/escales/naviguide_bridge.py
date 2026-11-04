"""Read-only bridge: NAVIGUIDE escale export → BI milestone rows.

When ``ESCALES_NAVIGUIDE_ENABLED`` is off, ``local_schedule_export`` is used
(no HTTP, no partner). The bridge never writes to NAVIGUIDE.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

import httpx

from ..escales_names import display_name
from .config import naviguide_api_base, naviguide_bridge_enabled, naviguide_json_path

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_FOLD = str.maketrans("àâäáéèêëíìîïóòôöúùûüçñ", "aaaaeeeeiiiioooouuuucn")


def _slug(name: str) -> str:
    folded = (name or "").strip().lower().translate(_FOLD)
    return _SLUG_RE.sub("-", folded).strip("-") or "escale"

LOCAL_SCHEDULE: dict[str, Any] = {
    "version": 1,
    "provider": "local",
    "escales": [
        {
            "milestone_id": "dep-mayotte",
            "name": "Mayotte",
            "slug": "mayotte",
            "lat": -12.78,
            "lon": 45.22,
            "arrival_iso": "2026-09-01T08:00:00+00:00",
            "flag": True,
        },
        {
            "milestone_id": "dep-fort-de-france",
            "name": "Fort-de-France",
            "slug": "fort-de-france",
            "lat": 14.6,
            "lon": -61.07,
            "arrival_iso": "2026-08-15T08:00:00+00:00",
            "flag": True,
        },
        {
            "milestone_id": "dep-dakar",
            "name": "Dakar",
            "slug": "dakar",
            "lat": 14.6937,
            "lon": -17.4441,
            "arrival_iso": "2026-12-01T08:00:00+00:00",
            "flag": True,
        },
        {
            "milestone_id": "dep-lorient",
            "name": "Lorient",
            "slug": "lorient",
            "lat": 47.748,
            "lon": -3.366,
            "arrival_iso": "2026-12-15T08:00:00+00:00",
            "flag": True,
        },
        {
            "milestone_id": "dep-pointe-a-pitre",
            "name": "Pointe-à-Pitre",
            "slug": "pointe-a-pitre",
            "lat": 16.2365,
            "lon": -61.5381,
            "arrival_iso": "2027-01-10T12:00:00+00:00",
            "flag": True,
        },
    ],
}


def local_schedule_export() -> dict[str, Any]:
    """Fallback schedule when the NAVIGUIDE bridge is disabled."""
    return dict(LOCAL_SCHEDULE)


def escales_to_milestones(export: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn an export payload into milestone-shaped dicts (no ledger write)."""
    rows: list[dict[str, Any]] = []
    for item in export.get("escales") or []:
        if not isinstance(item, dict):
            continue
        milestone_id = str(item.get("milestone_id") or "").strip()
        if not milestone_id:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            milestone_id = f"dep-{_slug(name)}"
        shown = display_name(str(item.get("slug") or milestone_id))
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


# Heures figées depuis l'horloge NAVIGUIDE au 12 novembre 2026, 08:00 UTC.
# Sources : voyageClock.js (buildVoyageClock), berryLegs.js (buildBerryLegs),
# routePlayhead.js, escales.js, geo.js, public/route.geojson.
# Une autre date d'horloge décale ces heures sans relancer le vent.
_CABIN_LEGS_PATH = Path(__file__).with_name("cabin_legs.json")
_LEG_TABLE: Optional[dict[str, Any]] = None


def cabin_leg_table() -> dict[str, Any]:
    """Table des jambes. Le fichier cite les pièces NAVIGUIDE dont il est tiré."""
    global _LEG_TABLE
    if _LEG_TABLE is None:
        _LEG_TABLE = json.loads(_CABIN_LEGS_PATH.read_text(encoding="utf-8"))
    return _LEG_TABLE


def _clock_origin():
    """08:00 UTC le jour de ``clock_start``. Même heure que le t0 de l'horloge."""
    import datetime as dt

    from .config import clock_start

    return dt.datetime.fromisoformat(f"{clock_start()}T08:00:00+00:00")


def _reference_t0():
    import datetime as dt

    raw = str(cabin_leg_table().get("t0") or "2026-11-12T08:00:00.000Z")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    moment = dt.datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment


def _shift_iso(raw: Any) -> str:
    """Date de la table, décalée si l'horloge de développement n'est pas le 12 novembre."""
    import datetime as dt

    text = str(raw or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = dt.datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    shifted = moment + (_clock_origin() - _reference_t0())
    return shifted.replace(microsecond=0).isoformat()


def clock_legs() -> list[dict[str, Any]]:
    """Une jambe par paire d'escales, datée par l'horloge du 12 novembre 2026.

    ``departure_iso`` est le départ de A (arrivée + séjour au quai).
    ``arrival_iso`` est l'arrivée en B. La capture d'une cabine suit le départ.
    """
    rows: list[dict[str, Any]] = []
    for item in cabin_leg_table().get("legs") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        row = dict(item)
        row["milestone_id"] = item["id"]
        row["departure_iso"] = _shift_iso(item.get("departure_iso"))
        row["arrival_iso"] = _shift_iso(item.get("arrival_iso"))
        row["capture_on"] = "departure"
        rows.append(row)
    return rows


def leg_by_id(leg_id: str) -> Optional[dict[str, Any]]:
    wanted = (leg_id or "").strip()
    if not wanted:
        return None
    for leg in clock_legs():
        if leg["id"] == wanted:
            return leg
    return None


def leg_departing_from(place: str) -> Optional[dict[str, Any]]:
    """Première jambe qui quitte cette escale, dans l'ordre de l'horloge."""
    slug = _slug(place)
    if len(slug) < 4:
        return None
    needle = f"-{slug}-"
    for leg in clock_legs():
        hay = f"-{leg.get('from_slug')}-"
        if needle in hay:
            return leg
    return None


def leg_milestone_meta(leg: dict[str, Any]) -> dict[str, Any]:
    """Champs du jalon de jambe. La capture lit ``departure_iso``."""
    title = f"{leg.get('from_name')} → {leg.get('to_name')}"
    return {
        "title": title,
        "display_name": title,
        "arrival_iso": leg.get("arrival_iso"),
        "departure_iso": leg.get("departure_iso"),
        "from": leg.get("from_slug"),
        "to": leg.get("to_slug"),
        "from_name": leg.get("from_name"),
        "to_name": leg.get("to_name"),
        "leg_kind": leg.get("kind"),
        "capture_on": "departure",
        "source": "clock",
    }


def legs_to_milestones(legs: Optional[list[dict[str, Any]]] = None) -> list[dict[str, Any]]:
    """Même forme que ``escales_to_milestones``, une ligne par jambe."""
    rows: list[dict[str, Any]] = []
    for leg in legs if legs is not None else clock_legs():
        meta = leg_milestone_meta(leg)
        rows.append(
            {
                "_id": leg["id"],
                "lat": None,
                "lon": None,
                "slug": leg["id"],
                **meta,
            }
        )
    return rows


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


async def sync_leg_shells() -> list[dict[str, Any]]:
    """Un jalon par jambe. La capture suit ``departure_iso``, pas l'arrivée."""
    from .pledges import get_ledger

    ledger = get_ledger()
    synced: list[dict[str, Any]] = []
    for row in legs_to_milestones():
        meta = {key: value for key, value in row.items() if key not in {"_id", "slug", "lat", "lon"}}
        doc = await ledger.ensure_milestone(row["_id"], meta=meta)
        synced.append(doc)
    return synced
