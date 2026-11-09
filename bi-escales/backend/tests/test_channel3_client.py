"""Channel3 money parsing — native currency, no invented EUR goals."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.channel3_client import _parse_money, product_to_gear_feature


def test_parse_money_rest_usd():
    parsed = _parse_money({"price": 29.99, "currency": "USD"})
    assert parsed == ("29.99", "USD")


def test_parse_money_ucp_minor_units_gbp():
    parsed = _parse_money({"amount": 4599, "currency": "GBP"})
    assert parsed == ("45.99", "GBP")


def test_product_to_gear_feature_usd_no_goal_eur():
    feature = product_to_gear_feature(
        {
            "title": "Marine shackle",
            "offers": [{"price": {"price": 9.99, "currency": "USD"}, "url": "https://buy.example/x"}],
        },
        query="shackle",
    )
    assert feature is not None
    props = feature["properties"]
    assert props["channel3_price"] == "9.99"
    assert props["channel3_currency"] == "USD"
    assert props.get("goal_currency") == "USD"
    assert "goal_eur" not in props
    assert "channel3_price_eur" not in props


def test_product_to_gear_feature_eur_keeps_goal_eur():
    feature = product_to_gear_feature(
        {
            "title": "Dive computer",
            "price": {"price": 120.0, "currency": "EUR"},
        },
        query="dive",
    )
    props = feature["properties"]
    assert props["goal_eur"] == "120.00"
    assert props["channel3_price_eur"] == "120.00"
    assert props["channel3_currency"] == "EUR"


def test_product_to_gear_feature_missing_price_no_invented_goal():
    feature = product_to_gear_feature({"title": "Mystery item"}, query="gear")
    props = feature["properties"]
    assert props.get("goal_eur") is None
    assert props.get("channel3_price") is None
