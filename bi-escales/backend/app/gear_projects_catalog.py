"""Expedition gear items (Channel3) with sandbox seed and optional live catalog search."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from app.channel3_catalog import get_catalog_item
from app.channel3_urls import normalize_channel3_product_url

_SEED = Path(__file__).resolve().parents[1] / "static" / "gear-projects.seed.json"
_SEED_CATALOG_PRODUCT: dict[str, str] = {
    "gear-dry-bag-expedition": "zRl9jHd",
    "gear-marine-binoculars": "ySwJYWZ",
}
_BUNDLED = Path(__file__).resolve().parents[2] / "frontend" / "public" / "bi-projects.geojson"

_cache: dict[str, Any] = {"at": 0.0, "payload": None}
_CACHE_TTL = 900.0


def _gear_props(props: dict) -> dict[str, Any]:
    kind = str(props.get("project_kind") or "").strip()
    if kind != "gear_project":
        return {}
    goal = str(props.get("goal_eur") or props.get("channel3_price_eur") or "").strip()
    channel3_price = str(props.get("channel3_price") or "").strip()
    channel3_currency = str(
        props.get("channel3_currency") or props.get("goal_currency") or ""
    ).strip().upper()
    goal_currency = "EUR" if goal else (channel3_currency or None)
    buy_source = props.get("channel3_buy_url") or props.get("channel3_url")
    if kind == "gear_project":
        buy_source = buy_source or props.get("url")
    return {
        "project_kind": kind or None,
        "goal_eur": goal or None,
        "goal_currency": goal_currency,
        "channel3_price": channel3_price or None,
        "channel3_currency": channel3_currency or None,
        "channel3_image_url": str(props.get("channel3_image_url") or props.get("channel3_photo") or "").strip() or None,
        "channel3_buy_url": normalize_channel3_product_url(buy_source),
        "channel3_product_name": str(props.get("channel3_product_name") or "").strip() or None,
    }


def _enrich_seed_props(props: dict) -> dict:
    """Merge catalogue prices and product URLs onto sandbox gear seed rows."""
    out = dict(props)
    if str(out.get("project_kind") or "").strip() != "gear_project":
        return out
    project_id = str(out.get("id") or "").strip()
    product_id = str(out.get("channel3_product_id") or _SEED_CATALOG_PRODUCT.get(project_id) or "").strip()
    if product_id:
        out["channel3_product_id"] = product_id
        catalog = get_catalog_item(product_id, public_only=True)
        if catalog:
            buy = normalize_channel3_product_url(catalog.get("channel3_buy_url"))
            if buy:
                out["channel3_buy_url"] = buy
                out["url"] = buy
            price = str(catalog.get("price_display") or "").strip()
            currency = str(catalog.get("price_currency") or "").strip().upper()
            if price:
                out["channel3_price"] = price
                out["channel3_currency"] = currency
                if currency == "EUR" and not out.get("channel3_price_eur"):
                    out["channel3_price_eur"] = price
                elif currency != "EUR":
                    out.setdefault("goal_currency", currency)
    for key in ("url", "channel3_buy_url"):
        cleaned = normalize_channel3_product_url(out.get(key))
        if cleaned:
            out[key] = cleaned
        else:
            out.pop(key, None)
    return out


def merge_gear_properties(props: dict) -> dict[str, Any]:
    """Attach gear / Channel3 fields when present on a GeoJSON feature."""
    out = _enrich_seed_props(props)
    for key, value in _gear_props(out).items():
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


def _funding_minors(
    amount: str,
    goal: str,
    *,
    amount_currency: str,
    goal_currency: str,
) -> Optional[tuple[int, int]]:
    """Minor units of one currency. Mismatched currencies are not comparable."""
    pledge_ccy = str(amount_currency or "EUR").strip().upper()
    goal_ccy = str(goal_currency or "EUR").strip().upper()
    if pledge_ccy != goal_ccy:
        return None
    from app.channel3_paypal import major_string_to_minor

    return (
        major_string_to_minor(str(amount), pledge_ccy),
        major_string_to_minor(str(goal), goal_ccy),
    )


def funded_percent(
    amount: str,
    goal: str,
    *,
    amount_currency: str = "EUR",
    goal_currency: str = "EUR",
) -> Optional[int]:
    """Floored progress when pledge and goal share a currency. 100 only when minors are covered."""
    pair = _funding_minors(
        amount,
        goal,
        amount_currency=amount_currency,
        goal_currency=goal_currency,
    )
    if pair is None:
        return None
    funded_minor, target_minor = pair
    if target_minor <= 0:
        return None
    if funded_minor >= target_minor:
        return 100
    return (funded_minor * 100) // target_minor


def is_fully_funded_amount(
    amount: str,
    goal: str,
    *,
    amount_currency: str = "EUR",
    goal_currency: str = "EUR",
) -> bool:
    """True only when funded minor units cover the target. No rounding."""
    pair = _funding_minors(
        amount,
        goal,
        amount_currency=amount_currency,
        goal_currency=goal_currency,
    )
    if pair is None:
        return False
    funded_minor, target_minor = pair
    return target_minor > 0 and funded_minor >= target_minor


def reset_gear_catalog_cache() -> None:
    _cache["at"] = 0.0
    _cache["payload"] = None


async def sanitize_public_gear_collection(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach funding progress; strip buy/Page URLs unless fully funded (never the Channel3 homepage)."""
    from app.channel3_funding import fund_snapshot_for_project
    from app.channel3_public import apply_buy_link_policy

    features_out: list[dict] = []
    for feature in payload.get("features") or []:
        if not isinstance(feature, dict):
            continue
        props = dict(feature.get("properties") or {})
        pid = str(props.get("id") or "").strip()
        raw_buy = normalize_channel3_product_url(props.get("channel3_buy_url"))
        props.pop("url", None)
        if pid:
            fund = await fund_snapshot_for_project(pid)
            goal = str(props.get("goal_eur") or props.get("channel3_price") or "").strip()
            goal_ccy = (
                "EUR"
                if props.get("goal_eur")
                else str(props.get("channel3_currency") or props.get("goal_currency") or "EUR").upper()
            )
            fund_ccy = str(fund.get("currency") or "EUR").upper()
            captured = str(fund.get("captured_eur") or fund.get("amount_eur") or "0")
            pct = (
                funded_percent(captured, goal, amount_currency=fund_ccy, goal_currency=goal_ccy)
                if goal
                else None
            )
            fully = bool(goal) and is_fully_funded_amount(
                captured,
                goal,
                amount_currency=fund_ccy,
                goal_currency=goal_ccy,
            )
            if pct is not None:
                props["funded_pct"] = pct
            props["fully_funded"] = fully
            props = apply_buy_link_policy(props, fully_funded=fully, buy_url=raw_buy)
            if fully and props.get("channel3_buy_url"):
                props["url"] = props["channel3_buy_url"]
        else:
            props = apply_buy_link_policy(props, fully_funded=False, buy_url=raw_buy)
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
