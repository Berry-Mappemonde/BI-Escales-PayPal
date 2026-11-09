"""Channel3 catalogue and wishlists (C3-05) — behind feature flags."""
from __future__ import annotations

from typing import Annotated, Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.channel3_catalog import get_catalog_item, lookup_catalog_by_project_id
from app.channel3_funding import enrich_item_funding, fund_snapshot_for_project
from app.channel3_public import apply_buy_link_policy
from app.channel3_wishlists import (
    WishlistError,
    add_wishlist_item,
    create_wishlist,
    enrich_treasurer_wishlist,
    get_wishlist,
    list_wishlists,
    public_catalog_payload,
    public_wishlist_payload,
    remove_wishlist_item,
    set_wishlist_published,
)
from app.escales.config import channel3_enabled, wishlists_enabled
from app.openapi_metadata import path_param, route_docs, with_example

router = APIRouter(tags=["channel3-wishlists"])

_PRODUCT_ID = "Gf8pNpL"
_PROJECT_ID = "gear-c3-gf8pnpl"
_WISHLIST_ID = "0123456789abcdef0123456789abcdef"
_LINE = {"channel3_product_id": _PRODUCT_ID, "quantity": 1}


class _CatalogueSeedLineDocs:
    """OpenAPI notes for one untyped catalogue seed object."""

    def __get_pydantic_json_schema__(self, core_schema, handler):
        schema = handler(core_schema)
        schema["description"] = (
            "Seed line copied from the Channel3 catalogue. "
            "channel3_product_id must already exist."
        )
        schema["example"] = _LINE
        schema["examples"] = [_LINE]
        return schema


class WishlistCreateIn(BaseModel):
    """Treasurer payload that creates an unpublished wishlist."""

    model_config = ConfigDict(
        json_schema_extra=with_example(
            {
                "title": "Galley stove",
                "slug": "galley-stove",
                "items": [_LINE],
            }
        )
    )
    title: str = Field(
        description="Public wishlist name shown to supporters.",
        examples=["Galley stove"],
        json_schema_extra={"example": "Galley stove"},
    )
    slug: str = Field(
        description="Unique slug. Stored case-folded.",
        examples=["galley-stove"],
        json_schema_extra={"example": "galley-stove"},
    )
    items: list[Annotated[dict[str, Any], _CatalogueSeedLineDocs()]] = Field(
        default_factory=list,
        description="Optional seed lines copied from the Channel3 catalogue.",
        examples=[[_LINE]],
        json_schema_extra={"example": [_LINE]},
    )


class WishlistItemIn(BaseModel):
    """One Channel3 catalogue line to add to a treasurer wishlist."""

    model_config = ConfigDict(
        json_schema_extra=with_example(
            {
                "channel3_product_id": _PRODUCT_ID,
                "quantity": 1,
                "target_amount_minor": 120000,
                "allow_optional": False,
            }
        )
    )
    channel3_product_id: str = Field(
        description="Channel3 catalogue product id.",
        title="Wishlist line Channel3 product id",
        examples=[_PRODUCT_ID],
        json_schema_extra={"example": _PRODUCT_ID},
    )
    quantity: int = Field(
        default=1,
        description="How many units of this catalogue line.",
        title="Wishlist line quantity",
        examples=[1],
        json_schema_extra={"example": 1},
    )
    target_amount_minor: Optional[int] = Field(
        default=None,
        description="Optional target amount in minor currency units.",
        examples=[120000],
        json_schema_extra={"example": 120000},
    )
    allow_optional: bool = Field(
        default=False,
        description="Allow a catalogue line that is marked optional.",
    )


class PublishIn(BaseModel):
    """Publish or unpublish a treasurer wishlist."""

    model_config = ConfigDict(
        json_schema_extra=with_example({"published": True})
    )
    published: bool = Field(
        default=True,
        description="When true, the wishlist is visible on the public wishlist routes.",
    )


def _require_flags() -> None:
    if not channel3_enabled() or not wishlists_enabled():
        raise HTTPException(status_code=404, detail="Channel3 wishlists are not enabled")


def _require_treasurer(request: Request) -> None:
    from app.routers.escales import _require_treasurer as _guard

    _guard(request)


def _wishlist_id(description: str, title: str):
    return path_param(description, _WISHLIST_ID, title)


_CATALOG_EXAMPLE = {
    "item_count": 1,
    "seed_item_count": 52,
    "items": [
        {
            "channel3_product_id": _PRODUCT_ID,
            "project_id": _PROJECT_ID,
            "fully_funded": False,
        }
    ],
}
_PUBLIC_WISHLIST = {
    "wishlist_id": _WISHLIST_ID,
    "slug": "galley-stove",
    "title": "Galley stove",
    "published": True,
    "items": [],
}
_TREASURER_WISHLIST = {
    "_id": _WISHLIST_ID,
    "title": "Galley stove",
    "slug": "galley-stove",
    "published": False,
    "items": [],
}


@router.get(
    "/channel3/catalog",
    operation_id="get_channel3_catalog",
    **route_docs(
        "List the public Channel3 catalogue",
        "Public catalogue rows with fund totals.",
        _CATALOG_EXAMPLE,
        schema_description="Public Channel3 catalogue. Buy links follow the funding policy.",
    ),
)
async def get_channel3_catalog():
    """Public Channel3 catalogue. 404 when Channel3 wishlists are disabled."""
    _require_flags()
    return await public_catalog_payload()


@router.get(
    "/channel3/catalog/{channel3_product_id}",
    operation_id="get_channel3_catalog_item",
    **route_docs(
        "Get one public catalogue item",
        "One public catalogue item with fund totals.",
        _CATALOG_EXAMPLE["items"][0],
        schema_description="Public catalogue item. The raw buy URL is omitted until funding policy allows it.",
        validation_loc=["path", "channel3_product_id"],
    ),
)
async def get_channel3_catalog_item(
    channel3_product_id: Annotated[
        str,
        path_param(
            "Channel3 catalogue product id.",
            _PRODUCT_ID,
            "Catalogue item Channel3 product id",
        ),
    ],
):
    """One public catalogue item and its fund snapshot."""
    _require_flags()
    catalog = get_catalog_item(channel3_product_id, public_only=True)
    if not catalog:
        raise HTTPException(status_code=404, detail="catalog item not found")
    fund = await fund_snapshot_for_project(catalog["project_id"])
    enriched = enrich_item_funding(catalog, fund)
    buy_url = catalog.get("channel3_buy_url")
    public = {k: v for k, v in enriched.items() if k != "channel3_buy_url"}
    return apply_buy_link_policy(public, fully_funded=bool(enriched.get("fully_funded")), buy_url=buy_url)


@router.get(
    "/channel3/catalog/by-project/{project_id}/fund",
    operation_id="get_channel3_item_fund",
    **route_docs(
        "Get fund totals for a catalogue project",
        "Public fund totals for one catalogue project.",
        {**_CATALOG_EXAMPLE["items"][0], "project_id": _PROJECT_ID},
        schema_description="Public fund totals for the catalogue project_id (PayPal target_id).",
        validation_loc=["path", "project_id"],
    ),
)
async def get_channel3_item_fund(
    project_id: Annotated[
        str,
        path_param(
            "Catalogue project id (PayPal target_id), for example gear-c3- plus the product id.",
            _PROJECT_ID,
            "Catalogue project id",
        ),
    ],
):
    """Public fund totals for one catalogue project_id (PayPal target_id)."""
    _require_flags()
    catalog = lookup_catalog_by_project_id(project_id, public_only=True)
    if not catalog:
        raise HTTPException(status_code=404, detail="catalog item not found")
    fund = await fund_snapshot_for_project(project_id)
    enriched = enrich_item_funding(catalog, fund)
    buy_url = catalog.get("channel3_buy_url")
    public = {k: v for k, v in enriched.items() if k != "channel3_buy_url"}
    return apply_buy_link_policy(public, fully_funded=bool(enriched.get("fully_funded")), buy_url=buy_url)


@router.get(
    "/wishlists",
    **route_docs(
        "List published wishlists",
        "Published wishlists only.",
        {"wishlists": [_PUBLIC_WISHLIST]},
        schema_description="Published wishlists. Unpublished rows are omitted.",
    ),
)
async def get_public_wishlists():
    """Published wishlists. 404 when Channel3 wishlists are disabled."""
    _require_flags()
    rows = await list_wishlists(published_only=True)
    return {"wishlists": [await public_wishlist_payload(row) for row in rows]}


@router.get(
    "/wishlists/{wishlist_id}",
    operation_id="get_public_wishlist",
    **route_docs(
        "Get one published wishlist",
        "One published wishlist.",
        _PUBLIC_WISHLIST,
        schema_description="Public wishlist payload. Unpublished wishlists are 404.",
        validation_loc=["path", "wishlist_id"],
    ),
)
async def get_public_wishlist(
    wishlist_id: Annotated[str, _wishlist_id("Published wishlist id.", "Public wishlist id")],
):
    """One published wishlist. Unpublished ids respond 404."""
    _require_flags()
    try:
        row = await get_wishlist(wishlist_id)
    except WishlistError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not row.get("published"):
        raise HTTPException(status_code=404, detail="wishlist not found")
    return await public_wishlist_payload(row)


@router.get(
    "/treasurer/wishlists",
    operation_id="treasurer_list_wishlists",
    **route_docs(
        "List treasurer wishlists",
        "Every wishlist, published or not.",
        {"wishlists": [_TREASURER_WISHLIST]},
        schema_description="Treasurer wishlist list, including unpublished rows.",
    ),
)
async def treasurer_list_wishlists(request: Request):
    """All wishlists for the treasurer, including unpublished ones."""
    _require_flags()
    _require_treasurer(request)
    rows = await list_wishlists(published_only=False)
    return {"wishlists": [enrich_treasurer_wishlist(row) for row in rows]}


@router.post(
    "/treasurer/wishlists",
    operation_id="treasurer_create_wishlist",
    **route_docs(
        "Create a treasurer wishlist",
        "Created wishlist. It starts unpublished.",
        _TREASURER_WISHLIST,
        schema_description="Stored wishlist document. published is false until the publish route.",
        validation_loc=["body", "title"],
        body_description="Title, unique slug, and optional catalogue seed lines.",
        body_example={"title": "Galley stove", "slug": "galley-stove", "items": [_LINE]},
    ),
)
async def treasurer_create_wishlist(request: Request, body: WishlistCreateIn):
    """Create an unpublished wishlist. The slug must be unique."""
    _require_flags()
    _require_treasurer(request)
    try:
        return await create_wishlist(title=body.title, slug=body.slug, items=body.items)
    except (WishlistError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/treasurer/wishlists/{wishlist_id}/items",
    operation_id="treasurer_add_wishlist_item",
    **route_docs(
        "Add a wishlist line",
        "Wishlist after the line is added or replaced.",
        _TREASURER_WISHLIST,
        schema_description="Stored wishlist after the catalogue line is added.",
        validation_loc=["path", "wishlist_id"],
        body_description="Catalogue line to add. The same product id replaces an existing line.",
        body_example={
            "channel3_product_id": _PRODUCT_ID,
            "quantity": 1,
            "target_amount_minor": 120000,
            "allow_optional": False,
        },
    ),
)
async def treasurer_add_wishlist_item(
    request: Request,
    wishlist_id: Annotated[
        str,
        _wishlist_id("Wishlist that receives the catalogue line.", "Wishlist id for adding an item"),
    ],
    body: WishlistItemIn,
):
    """Add or replace one catalogue line on a treasurer wishlist."""
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
    except (WishlistError, ValueError) as exc:
        code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.delete(
    "/treasurer/wishlists/{wishlist_id}/items/{channel3_product_id}",
    operation_id="treasurer_remove_wishlist_item",
    **route_docs(
        "Remove a wishlist line",
        "Wishlist after the line is removed.",
        _TREASURER_WISHLIST,
        schema_description="Stored wishlist after the catalogue line is removed.",
        validation_loc=["path", "wishlist_id"],
    ),
)
async def treasurer_remove_wishlist_item(
    request: Request,
    wishlist_id: Annotated[
        str,
        _wishlist_id("Wishlist that loses the catalogue line.", "Wishlist id for removing an item"),
    ],
    channel3_product_id: Annotated[
        str,
        path_param(
            "Channel3 product id to remove from the wishlist.",
            _PRODUCT_ID,
            "Channel3 product id removed from a wishlist",
        ),
    ],
):
    """Remove one catalogue line. 404 when the wishlist or the line is missing."""
    _require_flags()
    _require_treasurer(request)
    try:
        return await remove_wishlist_item(wishlist_id, channel3_product_id)
    except WishlistError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/treasurer/wishlists/{wishlist_id}/publish",
    operation_id="treasurer_publish_wishlist",
    **route_docs(
        "Publish or unpublish a wishlist",
        "Wishlist after the published flag changes.",
        {**_TREASURER_WISHLIST, "published": True},
        schema_description="Stored wishlist after published is set.",
        validation_loc=["path", "wishlist_id"],
        body_description="Whether the wishlist should be visible on the public routes.",
        body_example={"published": True},
    ),
)
async def treasurer_publish_wishlist(
    request: Request,
    wishlist_id: Annotated[
        str,
        _wishlist_id("Wishlist to publish or unpublish.", "Wishlist id to publish"),
    ],
    body: PublishIn,
):
    """Set the published flag. Publishing rejects lines that still need confirmation."""
    _require_flags()
    _require_treasurer(request)
    try:
        return await set_wishlist_published(wishlist_id, published=body.published)
    except WishlistError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
