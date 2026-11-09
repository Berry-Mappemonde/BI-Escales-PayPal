"""Channel3 catalogue and wishlists (C3-05) — behind feature flags."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.channel3_catalog import get_catalog_item, lookup_catalog_by_project_id
from app.channel3_funding import enrich_item_funding, fund_snapshot_for_project
from app.channel3_public import apply_buy_link_policy
from app.channel3_wishlists import (
    WishlistError,
    add_wishlist_item,
    create_wishlist,
    get_wishlist,
    list_wishlists,
    public_catalog_payload,
    public_wishlist_payload,
    remove_wishlist_item,
    set_wishlist_published,
)
from app.escales.config import channel3_enabled, wishlists_enabled

router = APIRouter(tags=["channel3-wishlists"])


def _require_flags() -> None:
    if not channel3_enabled() or not wishlists_enabled():
        raise HTTPException(status_code=404, detail="Channel3 wishlists are not enabled")


def _require_treasurer(request: Request) -> None:
    from app.routers.escales import _require_treasurer as _guard

    _guard(request)


class WishlistCreateIn(BaseModel):
    title: str
    slug: str
    items: list[dict[str, Any]] = Field(default_factory=list)


class WishlistItemIn(BaseModel):
    channel3_product_id: str
    quantity: int = 1
    target_amount_minor: Optional[int] = None
    allow_optional: bool = False


class PublishIn(BaseModel):
    published: bool = True


@router.get("/channel3/catalog")
async def get_channel3_catalog():
    _require_flags()
    return await public_catalog_payload()


@router.get("/channel3/catalog/{channel3_product_id}")
async def get_channel3_catalog_item(channel3_product_id: str):
    _require_flags()
    catalog = get_catalog_item(channel3_product_id, public_only=True)
    if not catalog:
        raise HTTPException(status_code=404, detail="catalog item not found")
    fund = await fund_snapshot_for_project(catalog["project_id"])
    enriched = enrich_item_funding(catalog, fund)
    buy_url = catalog.get("channel3_buy_url")
    public = {k: v for k, v in enriched.items() if k != "channel3_buy_url"}
    return apply_buy_link_policy(public, fully_funded=bool(enriched.get("fully_funded")), buy_url=buy_url)


@router.get("/channel3/catalog/by-project/{project_id}/fund")
async def get_channel3_item_fund(project_id: str):
    """Public fund totals for one catalogue ``project_id`` (PayPal ``target_id``)."""
    _require_flags()
    catalog = lookup_catalog_by_project_id(project_id, public_only=True)
    if not catalog:
        raise HTTPException(status_code=404, detail="catalog item not found")
    fund = await fund_snapshot_for_project(project_id)
    enriched = enrich_item_funding(catalog, fund)
    buy_url = catalog.get("channel3_buy_url")
    public = {k: v for k, v in enriched.items() if k != "channel3_buy_url"}
    return apply_buy_link_policy(public, fully_funded=bool(enriched.get("fully_funded")), buy_url=buy_url)


@router.get("/wishlists")
async def get_public_wishlists():
    _require_flags()
    rows = await list_wishlists(published_only=True)
    return {"wishlists": [await public_wishlist_payload(row) for row in rows]}


@router.get("/wishlists/{wishlist_id}")
async def get_public_wishlist(wishlist_id: str):
    _require_flags()
    try:
        row = await get_wishlist(wishlist_id)
    except WishlistError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not row.get("published"):
        raise HTTPException(status_code=404, detail="wishlist not found")
    return await public_wishlist_payload(row)


@router.get("/treasurer/wishlists")
async def treasurer_list_wishlists(request: Request):
    _require_flags()
    _require_treasurer(request)
    rows = await list_wishlists(published_only=False)
    return {"wishlists": rows}


@router.post("/treasurer/wishlists")
async def treasurer_create_wishlist(request: Request, body: WishlistCreateIn):
    _require_flags()
    _require_treasurer(request)
    try:
        return await create_wishlist(title=body.title, slug=body.slug, items=body.items)
    except WishlistError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/treasurer/wishlists/{wishlist_id}/items")
async def treasurer_add_wishlist_item(request: Request, wishlist_id: str, body: WishlistItemIn):
    _require_flags()
    _require_treasurer(request)
    try:
        return await add_wishlist_item(
            wishlist_id,
            channel3_product_id=body.channel3_product_id,
            quantity=body.quantity,
            target_amount_minor=body.target_amount_minor,
            allow_optional=body.allow_optional,
        )
    except WishlistError as exc:
        code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.delete("/treasurer/wishlists/{wishlist_id}/items/{channel3_product_id}")
async def treasurer_remove_wishlist_item(request: Request, wishlist_id: str, channel3_product_id: str):
    _require_flags()
    _require_treasurer(request)
    try:
        return await remove_wishlist_item(wishlist_id, channel3_product_id)
    except WishlistError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/treasurer/wishlists/{wishlist_id}/publish")
async def treasurer_publish_wishlist(request: Request, wishlist_id: str, body: PublishIn):
    _require_flags()
    _require_treasurer(request)
    try:
        return await set_wishlist_published(wishlist_id, published=body.published)
    except WishlistError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
