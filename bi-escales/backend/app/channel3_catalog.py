"""Channel3 expedition catalogue (C3-02 seed) — in-kind funding targets, no checkout."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app.channel3_paypal import minor_to_major_display, minor_units_for_major

_SEED = Path(__file__).resolve().parents[1] / "static" / "channel3-catalogue.seed.json"
_CORE_CATEGORIES = frozenset({"accastillage", "crew_safety"})
_OPTIONAL_CATEGORIES = frozenset({"crew_clothing"})


def project_id_for_product(channel3_product_id: str) -> str:
    token = str(channel3_product_id or "").strip()
    return f"gear-c3-{token.casefold()}"


def _normalize_item(raw: dict[str, Any]) -> dict[str, Any]:
    pid = str(raw.get("channel3_product_id") or "").strip()
    category = str(raw.get("category") or "").strip()
    currency = str(raw.get("currency") or "EUR").strip().upper()
    minor = minor_units_for_major(float(raw["price"]), currency)
    qty = int(raw.get("quantity") or 1)
    optional = category in _OPTIONAL_CATEGORIES
    return {
        "channel3_product_id": pid,
        "project_id": project_id_for_product(pid),
        "name": str(raw.get("name") or "").strip(),
        "category": category,
        "catalog_optional": optional,
        "core_catalogue": category in _CORE_CATEGORIES,
        "why_needed": str(raw.get("why_needed") or "").strip() or None,
        "quantity_needed": qty,
        "merchant": str(raw.get("merchant") or "").strip() or None,
        "merchant_country": str(raw.get("merchant_country") or "").strip().upper() or None,
        "unit_price_amount_minor": minor,
        "price_amount_minor": minor,
        "price_currency": currency,
        "price_display": minor_to_major_display(minor, currency),
        "catalog_default_target_amount_minor": minor * qty,
        "catalog_default_target_currency": currency,
        "image_url": str(raw.get("image_url") or raw.get("image") or "").strip() or None,
        "caution": str(raw.get("caution") or "").strip() or None,
        "max_commission_rate": raw.get("max_commission_rate"),
        "channel3_buy_url": str(raw.get("product_url") or "").strip() or None,
    }


def load_catalog_seed() -> dict[str, Any]:
    try:
        payload = json.loads(_SEED.read_text(encoding="utf-8"))
    except OSError:
        return {"items": []}
    items = payload.get("items") if isinstance(payload, dict) else []
    if not isinstance(items, list):
        items = []
    normalized = [_normalize_item(row) for row in items if isinstance(row, dict)]
    return {
        "generated_at": payload.get("generated_at") if isinstance(payload, dict) else None,
        "item_count": len(normalized),
        "items": normalized,
    }


def list_catalog_items(*, include_optional: bool = True) -> list[dict[str, Any]]:
    rows = load_catalog_seed().get("items") or []
    if include_optional:
        return list(rows)
    return [row for row in rows if row.get("core_catalogue")]


def get_catalog_item(channel3_product_id: str) -> Optional[dict[str, Any]]:
    token = str(channel3_product_id or "").strip()
    for row in list_catalog_items():
        if row["channel3_product_id"] == token:
            return dict(row)
    return None


def lookup_catalog_by_project_id(project_id: str) -> Optional[dict[str, Any]]:
    token = str(project_id or "").strip().casefold()
    for row in list_catalog_items():
        if str(row.get("project_id") or "").casefold() == token:
            return dict(row)
    return None


def default_wishlist_seed_items() -> list[dict[str, Any]]:
    """Core catalogue only — optional ``crew_clothing`` excluded from default lists."""
    return [
        {
            "channel3_product_id": row["channel3_product_id"],
            "quantity": row["quantity_needed"],
            "target_amount_minor": row["catalog_default_target_amount_minor"],
            "target_currency": row["catalog_default_target_currency"],
        }
        for row in list_catalog_items(include_optional=False)
    ]
