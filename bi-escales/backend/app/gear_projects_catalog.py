"""Expedition gear items (Channel3) with sandbox seed and optional live catalog search."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx

_SEED = Path(__file__).resolve().parents[1] / "static" / "gear-projects.seed.json"
_BUNDLED = Path(__file__).resolve().parents[2] / "frontend" / "public" / "bi-projects.geojson"

_cache: dict[str, Any] = {"at": 0.0, "payload": None}
_CACHE_TTL = 900.0


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


def load_gear_seed_collection() -> dict[str, Any]:
    try:
        payload = json.loads(_SEED.read_text(encoding="utf-8"))
    except OSError:
        payload = {"type": "FeatureCollection", "features": []}
    features = payload.get("features") if isinstance(payload, dict) else []
    if not isinstance(features, list):
        features = []
    normalized: list[dict] = []
    for raw in features:
        if not isinstance(raw, dict):
            continue
        props = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
        project_id = str(props.get("id") or "").strip()
        if not project_id:
            continue
        geometry = raw.get("geometry") if isinstance(raw.get("geometry"), dict) else {"type": "Point", "coordinates": [0, 0]}
        normalized.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": merge_gear_properties({**props, "id": project_id, "project_kind": "gear_project"}),
            }
        )
    return {"type": "FeatureCollection", "name": "Expedition gear (seed)", "features": normalized}


def _gear_search_queries() -> list[str]:
    raw = (os.environ.get("ESCALES_CHANNEL3_GEAR_QUERIES") or "").strip()
    if raw:
        return [part.strip() for part in raw.split(",") if part.strip()]
    return [
        "suunto dive computer",
        "waterproof dry bag 40l",
        "marine binoculars 7x50",
    ]


def _merge_feature_lists(seed: list[dict], extra: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for feature in seed:
        props = feature.get("properties") if isinstance(feature, dict) else {}
        pid = str((props or {}).get("id") or "").strip()
        if pid:
            by_id[pid] = feature
    for feature in extra:
        props = feature.get("properties") if isinstance(feature, dict) else {}
        pid = str((props or {}).get("id") or "").strip()
        if pid and pid not in by_id:
            by_id[pid] = feature
    return sorted(by_id.values(), key=lambda row: str((row.get("properties") or {}).get("id") or ""))


def lookup_project_fund_meta(project_id: str) -> Optional[dict[str, Any]]:
    """Goal and Channel3 links for public fund + UI (seed catalog first)."""
    token = (project_id or "").strip()
    if not token:
        return None
    for feature in load_gear_seed_collection().get("features") or []:
        props = feature.get("properties") if isinstance(feature, dict) else {}
        if str(props.get("id") or "").strip() != token:
            continue
        meta = _gear_props(props)
        if meta.get("goal_eur") or meta.get("channel3_buy_url") or meta.get("project_kind") == "gear_project":
            return {"project_id": token, **meta}
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


def funded_percent(amount_eur: str, goal_eur: str) -> int:
    try:
        amount = float(str(amount_eur).replace(",", "."))
        goal = float(str(goal_eur).replace(",", "."))
    except ValueError:
        return 0
    if goal <= 0:
        return 0
    return min(100, max(0, round((amount / goal) * 100)))


def reset_gear_catalog_cache() -> None:
    _cache["at"] = 0.0
    _cache["payload"] = None


async def get_gear_feature_collection(client: Optional[httpx.AsyncClient] = None) -> dict[str, Any]:
    """Public GET /gear payload: seed always, optional Channel3 search when enabled."""
    now = time.monotonic()
    cached = _cache.get("payload")
    if cached and now - float(_cache.get("at") or 0) < _CACHE_TTL:
        return cached

    seed = load_gear_seed_collection()
    source = "seed"
    live: list[dict] = []
    from .escales.config import channel3_enabled

    if channel3_enabled():
        from .channel3_client import search_gear_products

        try:
            live = await search_gear_products(_gear_search_queries(), limit_per_query=1, client=client)
            if live:
                source = "seed+channel3"
        except Exception:
            live = []

    features = _merge_feature_lists(list(seed.get("features") or []), live)
    payload = {
        "type": "FeatureCollection",
        "name": "Expedition gear",
        "source": source,
        "features": features,
    }
    _cache["at"] = now
    _cache["payload"] = payload
    return payload
