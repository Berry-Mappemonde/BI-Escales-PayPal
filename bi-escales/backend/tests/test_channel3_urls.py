from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.channel3_public import apply_buy_link_policy
from app.channel3_urls import (
    is_absolute_https_url,
    is_channel3_homepage_url,
    normalize_channel3_product_url,
)


def test_homepage_detection():
    assert is_channel3_homepage_url("https://trychannel3.com/")
    assert is_channel3_homepage_url("https://www.trychannel3.com")
    assert not is_channel3_homepage_url("https://buy.trychannel3.com/item")


def test_normalize_drops_homepage():
    assert normalize_channel3_product_url("https://trychannel3.com/") is None
    buy = "https://buy.trychannel3.com/x"
    assert normalize_channel3_product_url(buy) == buy


def test_apply_buy_link_never_returns_homepage():
    payload = apply_buy_link_policy(
        {},
        fully_funded=True,
        buy_url="https://trychannel3.com/",
    )
    assert "channel3_buy_url" not in payload


@pytest.mark.parametrize(
    "url,https_ok,normalized",
    [
        ("javascript:alert(1)", False, None),
        ("http://buy.trychannel3.com/x", False, None),
        ("data:text/html,hi", False, None),
        ("/relative", False, None),
        ("buy.trychannel3.com/x", False, None),
        ("https://buy.trychannel3.com/x", True, "https://buy.trychannel3.com/x"),
    ],
)
def test_https_only_product_urls(url: str, https_ok: bool, normalized: str | None) -> None:
    """Fails if normalize drops URL-parser scheme checks (mutation on is_absolute_https_url)."""
    assert is_absolute_https_url(url) is https_ok
    assert normalize_channel3_product_url(url) == normalized


def test_apply_buy_link_rejects_javascript_when_fully_funded() -> None:
    payload = apply_buy_link_policy(
        {},
        fully_funded=True,
        buy_url="javascript:alert(1)",
    )
    assert "channel3_buy_url" not in payload


def test_apply_buy_link_rejects_http_when_fully_funded() -> None:
    buy = "http://buy.trychannel3.com/x"
    payload = apply_buy_link_policy({}, fully_funded=True, buy_url=buy)
    assert "channel3_buy_url" not in payload
