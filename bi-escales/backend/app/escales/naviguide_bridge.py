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
