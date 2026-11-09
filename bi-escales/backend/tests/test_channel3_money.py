"""Channel3 money minor-unit normalization (C3-01)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.channel3_money import catalog_unit_price_minor, parse_money_minor, minor_to_major_str


def test_ucp_amount_is_minor_units():
    minor, ccy = parse_money_minor({"amount": 46995, "currency": "USD"})
    assert minor == 46995
    assert ccy == "USD"
    assert minor_to_major_str(minor) == "469.95"


def test_rest_price_is_major_units():
    minor, ccy = parse_money_minor({"price": 9.99, "currency": "USD"})
    assert minor == 999
    assert minor_to_major_str(minor) == "9.99"


def test_catalog_seed_price_to_minor():
    minor, ccy = catalog_unit_price_minor(price=16.99, currency="USD")
    assert minor == 1699
    assert ccy == "USD"
