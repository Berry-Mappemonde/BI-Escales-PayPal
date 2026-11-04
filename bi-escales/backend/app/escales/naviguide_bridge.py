"""Read-only bridge: NAVIGUIDE escale export → BI milestone rows.

When ``ESCALES_NAVIGUIDE_ENABLED`` is off, ``local_schedule_export`` is used
(no HTTP, no partner). The bridge never writes to NAVIGUIDE.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Optional

import httpx

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


_last_good: Optional[dict[str, Any]] = None


def reset_export_cache() -> None:
    global _last_good
    _last_good = None


def local_schedule_export(*, explicit_demo: bool = False) -> dict[str, Any]:
    """Demo schedule. It is not written over real milestones unless ``explicit_demo``."""
    payload = copy.deepcopy(LOCAL_SCHEDULE)
    payload["explicit_demo"] = explicit_demo
    return payload


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
        rows.append(
            {
                "_id": milestone_id,
                "title": item.get("name") or milestone_id,
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


def _remember_export(payload: dict[str, Any]) -> dict[str, Any]:
    global _last_good
    stored = copy.deepcopy(payload)
    _last_good = stored
    return copy.deepcopy(stored)


def _unavailable_export() -> dict[str, Any]:
    if _last_good is not None:
        payload = copy.deepcopy(_last_good)
        payload["stale"] = True
        return payload
    return {"version": 1, "provider": "unavailable", "escales": [], "explicit_demo": False}


async def fetch_naviguide_export(client: Optional[httpx.AsyncClient] = None) -> dict[str, Any]:
    """Load escales from a JSON file or NAVIGUIDE ``/escales/export``.

    HTTP failures keep the last successful export. They do not substitute the
    September 2026 demo dates. Demo data is returned only when the bridge is off
    (display) or when the caller sets ``explicit_demo``.
    """
    if not naviguide_bridge_enabled():
        return local_schedule_export()
    json_path = naviguide_json_path()
    if json_path:
        return _remember_export(load_export_from_path(json_path))
    base = naviguide_api_base()
    if not base:
        return _unavailable_export()
    url = f"{base}/escales/export"
    own = client is None
    http = client or httpx.AsyncClient()
    try:
        response = await http.get(url, timeout=15.0)
        response.raise_for_status()
        return _remember_export(parse_export(response.json()))
    except Exception:
        return _unavailable_export()
    finally:
        if own:
            await http.aclose()


def _skip_sync(payload: dict[str, Any]) -> bool:
    provider = payload.get("provider")
    if provider == "unavailable":
        return True
    if provider == "local" and not payload.get("explicit_demo"):
        return True
    return False


async def sync_milestone_shells(export: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """Ensure milestone documents exist for each exported escale (meta only).

    A failed NAVIGUIDE fetch and the implicit local demo do not overwrite
    arrival dates already stored on a milestone.
    """
    from .pledges import get_ledger

    payload = export if export is not None else await fetch_naviguide_export()
    ledger = get_ledger()
    if _skip_sync(payload):
        return await ledger.list_milestones()
    rows = escales_to_milestones(payload)
    synced: list[dict[str, Any]] = []
    for row in rows:
        doc = await ledger.ensure_milestone(
            row["_id"],
            meta={
                "title": row.get("title"),
                "arrival_iso": row.get("arrival_iso"),
                "lat": row.get("lat"),
                "lon": row.get("lon"),
                "source": row.get("source"),
            },
        )
        synced.append(doc)
    return synced
