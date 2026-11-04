"""Channel3 product search client.

API: POST https://api.trychannel3.com/v1/search (header x-api-key)
Docs: https://channel3.ai/docs/api-reference/v1/search
"""
from __future__ import annotations

import os
from typing import Any, Callable, Protocol

import httpx

CHANNEL3_SEARCH_URL = "https://api.trychannel3.com/v1/search"

# Onboard gear: authorize near departure; capture on departure day; void if stop cancelled.
ONBOARD_GEAR_QUERIES = (
    "sailing life jacket",
    "nautical chart",
    "marine LED flashlight",
    "boat first aid kit",
)


class HttpClient(Protocol):
    def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str], timeout: float) -> Any: ...


def channel3_api_key() -> str:
    return (os.environ.get("CHANNEL3_API_KEY") or "").strip()


def channel3_ready() -> bool:
    from .config import channel3_enabled

    return channel3_enabled() and bool(channel3_api_key())


def _price_eur(offer: dict[str, Any]) -> str | None:
    price = (offer or {}).get("price") or {}
    amount = price.get("price")
    currency = str(price.get("currency") or "EUR").upper()
    if amount is None:
        return None
    if currency not in ("EUR", "EURO"):
        return None
    return f"{float(amount):.2f}"


def normalize_product(product: dict[str, Any], *, query: str) -> dict[str, Any] | None:
    offers = product.get("offers") or []
    if not offers:
        return None
    offer = offers[0]
    amount = _price_eur(offer)
    if not amount:
        return None
    images = product.get("images") or []
    image = images[0] if images else None
    if isinstance(image, dict):
        image = image.get("url") or image.get("src")
    return {
        "id": str(product.get("id") or ""),
        "title": str(product.get("title") or "").strip(),
        "description": str(product.get("description") or "").strip(),
        "image_url": image,
        "amount_eur": amount,
        "currency": "EUR",
        "buy_url": str(offer.get("url") or ""),
        "query": query,
    }


async def search_gear(
    queries: tuple[str, ...] = ONBOARD_GEAR_QUERIES,
    *,
    client: HttpClient | None = None,
    api_key: str | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    key = (api_key if api_key is not None else channel3_api_key()).strip()
    if not key:
        return []
    own_client: httpx.AsyncClient | None = None
    if client is None:
        own_client = httpx.AsyncClient()
        client = own_client
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for query in queries:
            response = await client.post(  # type: ignore[union-attr]
                CHANNEL3_SEARCH_URL,
                json={"query": query, "limit": limit},
                headers={"x-api-key": key, "Content-Type": "application/json"},
                timeout=15.0,
            )
            response.raise_for_status()
            payload = response.json()
            for product in payload.get("products") or []:
                row = normalize_product(product, query=query)
                if not row or not row["id"] or row["id"] in seen:
                    continue
                seen.add(row["id"])
                items.append(row)
    finally:
        if own_client is not None:
            await own_client.aclose()
    return items
