"""Public Channel3 response policy — buy links and commission disclosure (C3-07)."""
from __future__ import annotations

from typing import Any, Iterable, Optional

from app.channel3_urls import normalize_channel3_product_url

CHANNEL3_BUY_DISCLOSURE = (
    "If you follow this Channel3 link and complete a purchase, the association may "
    "receive a referral commission from the merchant. The association never purchases "
    "through Channel3; supporters fund expedition gear in kind."
)

_BUY_URL_KEYS = (
    "channel3_buy_url",
    "product_url",
)


def apply_buy_link_policy(
    payload: dict[str, Any],
    *,
    fully_funded: bool,
    buy_url: Optional[str] = None,
) -> dict[str, Any]:
    """Strip checkout URLs unless the item is fully funded; attach disclosure when shown."""
    out = dict(payload)
    raw = (buy_url or out.get("channel3_buy_url") or out.get("product_url") or "").strip()
    link = normalize_channel3_product_url(raw) or ""
    if fully_funded and link:
        out["channel3_buy_url"] = link
        out["channel3_buy_disclosure"] = CHANNEL3_BUY_DISCLOSURE
        return out
    for key in _BUY_URL_KEYS:
        out.pop(key, None)
    out.pop("channel3_buy_disclosure", None)
    return out


def strip_buy_urls_deep(payload: Any) -> Any:
    """Remove buy URLs from nested structures (e.g. GeoJSON features) when not fully funded."""
    if isinstance(payload, dict):
        fully = bool(payload.get("fully_funded"))
        if any(payload.get(k) for k in _BUY_URL_KEYS) and not fully:
            cleaned = dict(payload)
            for key in _BUY_URL_KEYS:
                cleaned.pop(key, None)
            cleaned.pop("channel3_buy_disclosure", None)
            return cleaned
        return {k: strip_buy_urls_deep(v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [strip_buy_urls_deep(item) for item in payload]
    return payload
