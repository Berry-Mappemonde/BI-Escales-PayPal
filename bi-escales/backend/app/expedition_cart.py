"""Public expedition cart — gear catalogue rows plus voyage marinas with prices or labels."""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from app.channel3_catalog import get_catalog_item, list_catalog_items
from app.escales.captain import normalize_app_lang, simulated_unit
from app.gear_projects_catalog import load_gear_seed_collection, lookup_project_fund_meta

# Three sandbox gear projects + three C3-02 core catalogue lines (QA R3b-2).
_GEAR_SEED_IDS = (
    "gear-dive-computer-expedition",
    "gear-dry-bag-expedition",
    "gear-marine-binoculars",
)
_GEAR_CATALOG_PRODUCT_IDS = ("Gf8pNpL", "Mer1TUo", "pntIpmE")


def _price_unavailable_label(lang: str) -> str:
    return "prix indisponible" if normalize_app_lang(lang) == "fr" else "price unavailable"


def _line_from_amount(
    *,
    kind: str,
    row_id: str,
    description: str,
    amount: Optional[str],
    currency: str,
    lang: str,
) -> dict[str, Any]:
    amount_token = str(amount or "").strip()
    if amount_token:
        return {
            "kind": kind,
            "id": row_id,
            "description": description,
            "amount_eur": amount_token,
            "currency": currency,
            "price_label": None,
        }
    return {
        "kind": kind,
        "id": row_id,
        "description": description,
        "amount_eur": None,
        "currency": currency,
        "price_label": _price_unavailable_label(lang),
    }


def _gear_seed_line(props: dict[str, Any], lang: str) -> dict[str, Any]:
    project_id = str(props.get("id") or "").strip()
    title = str(props.get("title") or props.get("channel3_product_name") or project_id).strip()
    meta = lookup_project_fund_meta(project_id) or {}
    amount = (
        str(meta.get("channel3_price") or meta.get("goal_eur") or props.get("goal_eur") or "").strip()
        or str(props.get("channel3_price_eur") or props.get("channel3_price") or "").strip()
    )
    currency = str(
        meta.get("channel3_currency")
        or meta.get("goal_currency")
        or props.get("channel3_currency")
        or ("EUR" if props.get("goal_eur") else "EUR")
    ).strip().upper()
    return _line_from_amount(
        kind="gear",
        row_id=project_id,
        description=title,
        amount=amount or None,
        currency=currency,
        lang=lang,
    )


def _gear_catalog_line(product_id: str, lang: str) -> dict[str, Any]:
    row = get_catalog_item(product_id, public_only=True)
    if not row:
        return _line_from_amount(
            kind="gear",
            row_id=f"gear-c3-{product_id.casefold()}",
            description=product_id,
            amount=None,
            currency="EUR",
            lang=lang,
        )
    return _line_from_amount(
        kind="gear",
        row_id=str(row.get("project_id") or f"gear-c3-{product_id.casefold()}"),
        description=str(row.get("name") or product_id).strip(),
        amount=str(row.get("price_display") or "").strip() or None,
        currency=str(row.get("price_currency") or "EUR").strip().upper(),
        lang=lang,
    )


async def _marina_lines(lang: str) -> list[dict[str, Any]]:
    from app.bi_marinas_catalog import get_all_escale_marinas_geojson

    berth = simulated_unit("berth", lang)
    amount = str(berth.get("amount_eur") or "30.00")
    currency = str(berth.get("currency") or "EUR")
    collection = await get_all_escale_marinas_geojson()
    lines: list[dict[str, Any]] = []
    for feature in collection.get("features") or []:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        row_id = str(props.get("id") or props.get("osm_id") or "").strip()
        name = str(props.get("name") or row_id or "—").strip()
        lines.append(
            _line_from_amount(
                kind="marina",
                row_id=row_id or name,
                description=name,
                amount=amount,
                currency=currency,
                lang=lang,
            )
        )
    return lines


async def build_expedition_cart(lang: Optional[str] = None) -> dict[str, Any]:
    """Six gear rows and every voyage marina row with a price or an explicit unavailable label."""
    app_lang = normalize_app_lang(lang)
    gear_lines: list[dict[str, Any]] = []
    seed_by_id = {
        str((f.get("properties") or {}).get("id") or "").strip(): f
        for f in load_gear_seed_collection().get("features") or []
        if isinstance(f, dict)
    }
    for project_id in _GEAR_SEED_IDS:
        feature = seed_by_id.get(project_id)
        props = feature.get("properties") if isinstance(feature, dict) else {}
        if isinstance(props, dict):
            gear_lines.append(_gear_seed_line(props, app_lang))
    for product_id in _GEAR_CATALOG_PRODUCT_IDS:
        gear_lines.append(_gear_catalog_line(product_id, app_lang))
    marina_lines = await _marina_lines(app_lang)
    return {
        "currency": "EUR",
        "gear_count": len(gear_lines),
        "marina_count": len(marina_lines),
        "lines": [*gear_lines, *marina_lines],
    }


def build_expedition_cart_sync(lang: Optional[str] = None) -> dict[str, Any]:
    return asyncio.run(build_expedition_cart(lang))
