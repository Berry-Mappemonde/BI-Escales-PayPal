"""Channel3 UCP catalog search (#26) — expedition gear enrichment when enabled."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

import httpx

from app.channel3_money import minor_to_major_str, parse_money_major, parse_money_minor
from app.escales.config import channel3_api_key, channel3_enabled, channel3_mcp_url

_SLUG = re.compile(r"[^a-z0-9-]+")
_BLOCKED_CHANNEL3 = re.compile(
    r"(?:^|[/:])(?:checkout|checkouts|purchase|purchases|order|orders)(?:/|$|\?)",
    re.IGNORECASE,
)
_ALLOWED_MCP_TOOLS = frozenset({"search_catalog"})


class Channel3GuardError(RuntimeError):
    """Raised when a non read-only Channel3 endpoint is requested (C3-08)."""


def assert_channel3_read_only_url(url: str) -> None:
    """Only allow search/MCP read paths — never checkout, purchase, or order."""
    token = str(url or "").strip()
    if not token:
        raise Channel3GuardError("empty Channel3 URL")
    if _BLOCKED_CHANNEL3.search(token):
        raise Channel3GuardError(f"forbidden Channel3 endpoint: {token}")


def assert_channel3_mcp_tool(tool_name: str) -> None:
    if str(tool_name or "").strip() not in _ALLOWED_MCP_TOOLS:
        raise Channel3GuardError(f"forbidden Channel3 MCP tool: {tool_name}")


def _slug(text: str) -> str:
    token = _SLUG.sub("-", (text or "").strip().lower()).strip("-")
    return token or "item"


def _parse_money(raw: Any) -> Optional[tuple[str, str]]:
    """Legacy helper — major-unit display string + ISO currency."""
    return parse_money_major(raw)


def _walk_products(node: Any, out: list[dict]) -> None:
    if isinstance(node, dict):
        if "products" in node and isinstance(node["products"], list):
            for item in node["products"]:
                if isinstance(item, dict):
                    out.append(item)
        for value in node.values():
            _walk_products(value, out)
    elif isinstance(node, list):
        for item in node:
            _walk_products(item, out)


def _parse_mcp_products(body: str) -> list[dict]:
    products: list[dict] = []
    for line in body.splitlines():
        text = line.strip()
        if text.startswith("data:"):
            text = text[5:].strip()
        if not text or text == "[DONE]":
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        _walk_products(payload, products)
    if not products:
        try:
            _walk_products(json.loads(body), products)
        except json.JSONDecodeError:
            pass
    return products


def _first_offer(product: dict) -> dict:
    variants = product.get("variants")
    if isinstance(variants, list):
        for variant in variants:
            if isinstance(variant, dict):
                return variant
    offers = product.get("offers")
    if isinstance(offers, list) and offers and isinstance(offers[0], dict):
        return offers[0]
    return {}


def product_to_gear_feature(product: dict, *, query: str) -> Optional[dict]:
    title = str(product.get("title") or product.get("name") or query).strip()
    if not title:
        return None
    offer = _first_offer(product)
    buy_url = str(
        offer.get("url")
        or offer.get("buy_url")
        or product.get("url")
        or product.get("product_url")
        or ""
    ).strip()
    image = str(
        product.get("image_url")
        or product.get("image")
        or offer.get("image_url")
        or ""
    ).strip()
    money_raw = product.get("price") or offer.get("price") or product.get("min_price")
    money_minor = parse_money_minor(money_raw)
    money = _parse_money(money_raw)
    digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:10]
    gear_id = f"gear-c3-{_slug(title)[:32]}-{digest}"
    props: dict[str, Any] = {
        "id": gear_id,
        "title": title,
        "funder": "Channel3",
        "url": buy_url or "https://trychannel3.com/",
        "category_group": "Gear",
        "location": "Channel3",
        "description": f"Produit Channel3 (recherche « {query} »).",
        "project_kind": "gear_project",
        "channel3_image_url": image or None,
        "channel3_buy_url": buy_url or None,
        "channel3_product_name": title,
        "channel3_source": "live",
    }
    if money_minor:
        minor, currency = money_minor
        amount = minor_to_major_str(minor)
        props["price_amount_minor"] = minor
        props["price_currency"] = currency
        props["channel3_price"] = amount
        props["channel3_currency"] = currency
        if currency in {"EUR", "EURO"}:
            props["goal_eur"] = amount
            props["channel3_price_eur"] = amount
        else:
            props["goal_currency"] = currency
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [55.5, -20.9]},
        "properties": props,
    }


async def search_gear_products(
    queries: list[str],
    *,
    limit_per_query: int = 1,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict]:
    """Return GeoJSON-like gear features from Channel3 search_catalog (Token tier when keyed)."""
    if not channel3_enabled():
        return []
    assert_channel3_read_only_url(channel3_mcp_url())
    assert_channel3_mcp_tool("search_catalog")
    owns = client is None
    if owns:
        client = httpx.AsyncClient(timeout=25.0)
    assert client is not None
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    key = channel3_api_key()
    if key:
        headers["x-api-key"] = key
    features: list[dict] = []
    seen: set[str] = set()
    try:
        for query in queries:
            q = (query or "").strip()
            if not q:
                continue
            body = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "search_catalog",
                    "arguments": {
                        "meta": None,
                        "catalog": {
                            "query": q,
                            "pagination": {"limit": max(1, limit_per_query)},
                        },
                    },
                },
            }
            response = await client.post(channel3_mcp_url(), json=body, headers=headers)
            response.raise_for_status()
            for product in _parse_mcp_products(response.text)[:limit_per_query]:
                feature = product_to_gear_feature(product, query=q)
                if not feature:
                    continue
                pid = str(feature["properties"]["id"])
                if pid in seen:
                    continue
                seen.add(pid)
                features.append(feature)
    finally:
        if owns:
            await client.aclose()
    return features
