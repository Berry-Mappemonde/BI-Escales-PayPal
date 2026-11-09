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
    channel3_price = str(props.get("channel3_price") or "").strip()
    channel3_currency = str(
        props.get("channel3_currency") or props.get("goal_currency") or ""
    ).strip().upper()
    goal_currency = "EUR" if goal else (channel3_currency or None)
    return {
        "project_kind": str(props.get("project_kind") or "").strip() or None,
        "goal_eur": goal or None,
        "goal_currency": goal_currency,
        "channel3_price": channel3_price or None,
        "channel3_currency": channel3_currency or None,
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
    from app.channel3_catalog import lookup_catalog_by_project_id

    catalog = lookup_catalog_by_project_id(token)
    if catalog:
        goal_currency = str(catalog.get("price_currency") or "EUR")
        amount = str(catalog.get("price_display") or "")
        meta: dict[str, Any] = {
            "project_id": token,
            "project_kind": "gear_project",
            "channel3_product_id": catalog.get("channel3_product_id"),
            "channel3_product_name": catalog.get("name"),
            "channel3_price": amount,
            "channel3_currency": goal_currency,
            "price_amount_minor": catalog.get("price_amount_minor"),
            "price_currency": catalog.get("price_currency"),
            "channel3_buy_url": catalog.get("channel3_buy_url"),
            "channel3_image_url": catalog.get("image_url"),
            "goal_currency": goal_currency,
        }
        if goal_currency == "EUR":
            meta["goal_eur"] = amount
        return meta
    for feature in load_gear_seed_collection().get("features") or []:
        props = feature.get("properties") if isinstance(feature, dict) else {}
        if str(props.get("id") or "").strip() != token:
            continue
        meta = _gear_props(props)
        if (
            meta.get("goal_eur")
            or meta.get("channel3_price")
            or meta.get("channel3_buy_url")
            or meta.get("project_kind") == "gear_project"
        ):
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
        if (
            meta.get("goal_eur")
            or meta.get("channel3_price")
            or meta.get("channel3_buy_url")
            or meta.get("project_kind") == "gear_project"
        ):
            return {"project_id": token, **meta}
    return None


def funded_percent(
    amount: str,
    goal: str,
    *,
    amount_currency: str = "EUR",
    goal_currency: str = "EUR",
) -> Optional[int]:
    """Progress percent when pledge and goal share the same currency; otherwise unset."""
    pledge_ccy = str(amount_currency or "EUR").strip().upper()
    goal_ccy = str(goal_currency or "EUR").strip().upper()
    if pledge_ccy != goal_ccy:
        return None
    try:
        pledged = float(str(amount).replace(",", "."))
        target = float(str(goal).replace(",", "."))
    except ValueError:
        return None
    if target <= 0:
        return None
    return min(100, max(0, round((pledged / target) * 100)))


def reset_gear_catalog_cache() -> None:
    _cache["at"] = 0.0
    _cache["payload"] = None


async def sanitize_public_gear_collection(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip Channel3 buy URLs on public gear unless the item is fully funded."""
    from app.channel3_funding import fund_snapshot_for_project
    from app.channel3_public import apply_buy_link_policy

    features_out: list[dict] = []
    for feature in payload.get("features") or []:
        if not isinstance(feature, dict):
            continue
        props = dict(feature.get("properties") or {})
        pid = str(props.get("id") or "").strip()
        buy_url = str(props.get("channel3_buy_url") or "").strip() or None
        if buy_url and pid:
            fund = await fund_snapshot_for_project(pid)
            goal = str(props.get("goal_eur") or props.get("channel3_price") or "").strip()
            goal_ccy = (
                "EUR"
                if props.get("goal_eur")
                else str(props.get("channel3_currency") or props.get("goal_currency") or "EUR").upper()
            )
            fund_ccy = str(fund.get("currency") or "EUR").upper()
            pct = (
                funded_percent(
                    str(fund.get("captured_eur") or fund.get("amount_eur") or "0"),
                    goal,
                    amount_currency=fund_ccy,
                    goal_currency=goal_ccy,
                )
                if goal
                else None
            )
            fully = pct is not None and pct >= 100
            props = apply_buy_link_policy(props, fully_funded=fully, buy_url=buy_url)
        feature_out = {**feature, "properties": props}
        features_out.append(feature_out)
    return {**payload, "features": features_out}


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
