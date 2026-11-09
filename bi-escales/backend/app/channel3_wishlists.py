"""Wishlist business logic — treasurer CRUD and public published views."""
from __future__ import annotations

from typing import Any, Optional

from app.channel3_catalog import get_catalog_item, list_catalog_items
from app.channel3_funding import enrich_item_funding, fund_snapshot_for_project
from app.channel3_public import apply_buy_link_policy
from app.channel3_wishlist_store import get_wishlist_store, new_wishlist_id, normalize_wishlist_item
from app.escales.ledger import now_iso


class WishlistError(ValueError):
    pass


async def create_wishlist(*, title: str, slug: str, items: Optional[list[dict]] = None) -> dict:
    title_clean = (title or "").strip()
    slug_clean = (slug or "").strip().casefold()
    if not title_clean:
        raise WishlistError("title required")
    if not slug_clean:
        raise WishlistError("slug required")
    store = get_wishlist_store()
    for existing in await store.list_wishlists():
        if str(existing.get("slug") or "").casefold() == slug_clean:
            raise WishlistError("slug already exists")
    normalized_items: list[dict] = []
    for row in items or []:
        pid = str(row.get("channel3_product_id") or "").strip()
        catalog = get_catalog_item(pid)
        if not catalog:
            raise WishlistError(f"unknown catalog item {pid}")
        if catalog.get("needs_confirmation"):
            raise WishlistError(f"item {pid} is pending treasurer confirmation")
        if catalog.get("catalog_optional") and not row.get("allow_optional"):
            raise WishlistError(f"item {pid} is optional catalogue-only")
        normalized_items.append(normalize_wishlist_item(row, catalog))
    doc = {
        "_id": new_wishlist_id(),
        "title": title_clean,
        "slug": slug_clean,
        "published": False,
        "items": normalized_items,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    return await store.save_wishlist(doc)


async def list_wishlists(*, published_only: bool = False) -> list[dict]:
    rows = await get_wishlist_store().list_wishlists()
    if published_only:
        rows = [row for row in rows if row.get("published")]
    return rows


async def get_wishlist(wishlist_id: str) -> dict:
    row = await get_wishlist_store().get_wishlist(wishlist_id)
    if not row:
        raise WishlistError("wishlist not found")
    return row


async def set_wishlist_published(wishlist_id: str, *, published: bool) -> dict:
    row = await get_wishlist(wishlist_id)
    if published:
        for item in row.get("items") or []:
            pid = str(item.get("channel3_product_id") or "").strip()
            catalog = get_catalog_item(pid)
            if catalog and catalog.get("needs_confirmation"):
                raise WishlistError(f"wishlist item {pid} is pending confirmation")
    row["published"] = bool(published)
    row["updated_at"] = now_iso()
    return await get_wishlist_store().save_wishlist(row)


async def add_wishlist_item(
    wishlist_id: str,
    *,
    channel3_product_id: str,
    quantity: int,
    target_amount_minor: Optional[int] = None,
    allow_optional: bool = False,
) -> dict:
    row = await get_wishlist(wishlist_id)
    catalog = get_catalog_item(channel3_product_id)
    if not catalog:
        raise WishlistError("unknown catalog item")
    if catalog.get("needs_confirmation"):
        raise WishlistError("item pending treasurer confirmation")
    if catalog.get("catalog_optional") and not allow_optional:
        raise WishlistError("crew_clothing items require allow_optional")
    item = normalize_wishlist_item(
        {
            "channel3_product_id": channel3_product_id,
            "quantity": quantity,
            "target_amount_minor": target_amount_minor,
        },
        catalog,
    )
    items = [i for i in row.get("items") or [] if i.get("channel3_product_id") != channel3_product_id]
    items.append(item)
    row["items"] = items
    row["updated_at"] = now_iso()
    return await get_wishlist_store().save_wishlist(row)


async def remove_wishlist_item(wishlist_id: str, channel3_product_id: str) -> dict:
    row = await get_wishlist(wishlist_id)
    token = str(channel3_product_id or "").strip()
    items = [i for i in row.get("items") or [] if i.get("channel3_product_id") != token]
    if len(items) == len(row.get("items") or []):
        raise WishlistError("item not on wishlist")
    row["items"] = items
    row["updated_at"] = now_iso()
    return await get_wishlist_store().save_wishlist(row)


async def _public_item_from_catalog(
    catalog: dict[str, Any],
    wishlist_item: Optional[dict] = None,
) -> dict[str, Any]:
    fund = await fund_snapshot_for_project(catalog["project_id"])
    target_minor: Optional[int] = None
    target_ccy: Optional[str] = None
    line_qty: Optional[int] = None
    if wishlist_item:
        target_minor = int(wishlist_item.get("target_amount_minor") or 0)
        target_ccy = wishlist_item.get("target_currency")
        line_qty = int(wishlist_item.get("quantity") or 1)
    enriched = enrich_item_funding(
        catalog,
        fund,
        target_amount_minor=target_minor,
        target_currency=target_ccy,
    )
    if wishlist_item:
        enriched["quantity"] = line_qty
        enriched["quantity_needed"] = line_qty
        enriched["unit_price_amount_minor"] = int(
            wishlist_item.get("unit_price_amount_minor")
            or catalog.get("unit_price_amount_minor")
            or catalog.get("price_amount_minor")
            or 0
        )
    buy_url = catalog.get("channel3_buy_url")
    public = {k: v for k, v in enriched.items() if k != "channel3_buy_url"}
    return apply_buy_link_policy(public, fully_funded=bool(enriched.get("fully_funded")), buy_url=buy_url)


def _unavailable_wishlist_line(item: dict, *, reason: str) -> dict[str, Any]:
    return {
        "channel3_product_id": str(item.get("channel3_product_id") or "").strip() or None,
        "project_id": item.get("project_id"),
        "catalog_available": False,
        "unavailable_reason": reason,
        "quantity": int(item.get("quantity") or 1),
    }


async def public_wishlist_payload(row: dict) -> dict[str, Any]:
    items_out: list[dict] = []
    for item in row.get("items") or []:
        pid = str(item.get("channel3_product_id") or "")
        catalog = get_catalog_item(pid)
        if not catalog:
            items_out.append(_unavailable_wishlist_line(item, reason="removed_from_catalog"))
            continue
        if catalog.get("needs_confirmation"):
            items_out.append(_unavailable_wishlist_line(item, reason="needs_confirmation"))
            continue
        items_out.append(await _public_item_from_catalog(catalog, item))
    return {
        "wishlist_id": row["_id"],
        "slug": row.get("slug"),
        "title": row.get("title"),
        "published": bool(row.get("published")),
        "items": items_out,
        "updated_at": row.get("updated_at"),
    }


async def public_catalog_payload() -> dict[str, Any]:
    items = []
    for catalog in list_catalog_items(public_only=True):
        items.append(await _public_item_from_catalog(catalog))
    seed = {
        "item_count": len(items),
        "seed_item_count": len(list_catalog_items()),
        "items": items,
    }
    return seed
