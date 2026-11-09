from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.channel3_public import apply_buy_link_policy
from app.channel3_urls import is_channel3_homepage_url, normalize_channel3_product_url


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
