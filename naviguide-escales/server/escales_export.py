"""Export JSON des escales officielles pour BI Escales (lecture seule).

Aucun secret : le payload reprend le voyage officiel déjà servi par NAVIGUIDE.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPORT_VERSION = 1


def milestone_id_for_name(name: str) -> str:
    from escale_watch import slug

    return f"dep-{slug(name)}"


def stop_to_row(mark: dict[str, Any]) -> dict[str, Any]:
    name = str(mark.get("name") or "").strip()
    from escale_watch import slug

    key = slug(name)
    return {
        "milestone_id": f"dep-{key}",
        "name": name,
        "slug": key,
        "lat": mark.get("lat"),
        "lon": mark.get("lon"),
        "arrival_iso": mark.get("iso"),
        "flag": bool(mark.get("flag")),
    }


def build_export(stops: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for mark in stops or []:
        if not isinstance(mark, dict):
            continue
        if not str(mark.get("name") or "").strip():
            continue
        rows.append(stop_to_row(mark))
    return {
        "version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "provider": "NAVIGUIDE",
        "escales": rows,
    }


def export_from_marks(marks: list[dict[str, Any]] | None, clock: dict[str, Any] | None = None) -> dict[str, Any]:
    """Construit l'export à partir de marks bruts (tests ou voyage injecté)."""
    from film_script import official_dated_stops

    stops = official_dated_stops(marks, clock)
    return build_export(stops)


def export_official_escales() -> dict[str, Any]:
    """Escales datées du voyage Berry officiel."""
    from film_script import official_dated_stops
    from voyage_clock import OFFICIAL_VOYAGE_ID
    from voyage_store import load_voyage

    voy = load_voyage(OFFICIAL_VOYAGE_ID) or {}
    clock = voy.get("clock") if isinstance(voy, dict) else None
    marks = (clock or {}).get("marks") if isinstance(clock, dict) else None
    stops = official_dated_stops(marks, clock)
    return build_export(stops)


def write_export_file(path: str | Path, payload: dict[str, Any] | None = None) -> Path:
    """Écrit l'export sur disque (option poste / CI)."""
    target = Path(path)
    data = payload if payload is not None else export_official_escales()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target
