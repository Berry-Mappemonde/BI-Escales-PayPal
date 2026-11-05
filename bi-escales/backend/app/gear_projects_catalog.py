"""Expedition gear items (Channel3) stored as BI project features with funding goals."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

_BUNDLED = Path(__file__).resolve().parents[2] / "frontend" / "public" / "bi-projects.geojson"


def _gear_props(props: dict) -> dict[str, Any]:
    goal = str(props.get("goal_eur") or props.get("channel3_price_eur") or "").strip()
    return {
        "project_kind": str(props.get("project_kind") or "").strip() or None,
        "goal_eur": goal or None,
        "channel3_image_url": str(props.get("channel3_image_url") or props.get("channel3_photo") or "").strip() or None,
        "channel3_buy_url": str(props.get("channel3_buy_url") or props.get("channel3_url") or "").strip() or None,
        "channel3_product_name": str(props.get("channel3_product_name") or "").strip() or None,
    }


def merge_gear_properties(props: dict) -> dict[str, Any]:
    """Attach gear / Channel3 fields when present on a GeoJSON feature."""
    out = dict(props)
    for key, value in _gear_props(props).items():
        if value is not None:
            out[key] = value
    return out


def lookup_project_fund_meta(project_id: str) -> Optional[dict[str, Any]]:
    """Goal and Channel3 links for public fund + UI (bundled snapshot)."""
    token = (project_id or "").strip()
    if not token:
        return None
    try:
        bundled = json.loads(_BUNDLED.read_text(encoding="utf-8"))
    except OSError:
        return None
    for feature in bundled.get("features") or []:
        props = feature.get("properties") if isinstance(feature, dict) else {}
        if not isinstance(props, dict):
            continue
        if str(props.get("id") or "").strip() != token:
            continue
        meta = _gear_props(props)
        if meta.get("goal_eur") or meta.get("channel3_buy_url") or meta.get("project_kind") == "gear_project":
            return {"project_id": token, **meta}
        return None
    return None


def funded_percent(amount_eur: str, goal_eur: str) -> int:
    try:
        amount = float(str(amount_eur).replace(",", "."))
        goal = float(str(goal_eur).replace(",", "."))
    except ValueError:
        return 0
    if goal <= 0:
        return 0
    return min(100, max(0, round((amount / goal) * 100)))
