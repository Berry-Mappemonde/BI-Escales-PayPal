"""PayPal currency support for Channel3 catalogue pledges (native currency, no FX)."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# Allow-list: https://developer.paypal.com/reference/currency-codes/
PAYPAL_CURRENCY_CODES_URL = "https://developer.paypal.com/reference/currency-codes/"

PAYPAL_SUPPORTED_CURRENCY_CODES = frozenset(
    {
        "AUD",
        "BRL",
        "CAD",
        "CNY",
        "CZK",
        "DKK",
        "EUR",
        "HKD",
        "HUF",
        "ILS",
        "JPY",
        "MYR",
        "MXN",
        "TWD",
        "NZD",
        "NOK",
        "PHP",
        "PLN",
        "GBP",
        "SGD",
        "SEK",
        "CHF",
        "THB",
        "USD",
    }
)

PAYPAL_ZERO_DECIMAL_CURRENCIES = frozenset({"HUF", "JPY", "TWD"})

_AMOUNT_TWO_DP = re.compile(r"^\d+(?:\.\d{1,2})?$")
_AMOUNT_WHOLE = re.compile(r"^\d+$")


def paypal_currency_supported(currency: str) -> bool:
    token = str(currency or "").strip().upper()
    return bool(token) and token in PAYPAL_SUPPORTED_CURRENCY_CODES


def catalog_project_id(target_id: str) -> bool:
    return str(target_id or "").strip().casefold().startswith("gear-c3-")


def currency_uses_whole_units(currency: str) -> bool:
    return str(currency or "").strip().upper() in PAYPAL_ZERO_DECIMAL_CURRENCIES


def minor_units_for_major(price: float, currency: str) -> int:
    """Internal minor counter: whole units for JPY/HUF/TWD, else cents."""
    ccy = str(currency or "").strip().upper()
    value = Decimal(str(price))
    if currency_uses_whole_units(ccy):
        return int(value.quantize(Decimal("1")))
    return int((value * Decimal("100")).quantize(Decimal("1")))


def minor_to_major_display(minor: int, currency: str) -> str:
    ccy = str(currency or "").strip().upper()
    if currency_uses_whole_units(ccy):
        return str(int(minor))
    return f"{(Decimal(int(minor)) / Decimal('100')):.2f}"


def normalize_project_pledge_amount(raw: str, currency: str) -> str:
    """Validate supporter amount in the catalogue native currency."""
    text = (raw or "").strip()
    ccy = str(currency or "").strip().upper()
    if currency_uses_whole_units(ccy):
        if not _AMOUNT_WHOLE.match(text) and not _AMOUNT_TWO_DP.match(text):
            raise ValueError(f"amount must be a positive whole-number {ccy} amount")
        try:
            value = Decimal(text.replace(",", "."))
        except InvalidOperation as exc:
            raise ValueError(f"amount must be a positive whole-number {ccy} amount") from exc
        if value <= 0 or value != value.to_integral_value():
            raise ValueError(f"{ccy} amounts must be whole units without decimals")
        if value < 1:
            raise ValueError(f"amount must be at least 1 {ccy}")
        return str(int(value))
    if not _AMOUNT_TWO_DP.match(text):
        raise ValueError("amount_eur must be a positive amount with at most 2 decimal places")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("amount_eur must be a positive amount with at most 2 decimal places") from exc
    if value <= 0:
        raise ValueError("amount_eur must be a positive amount with at most 2 decimal places")
    if value < Decimal("1.00"):
        raise ValueError(f"amount must be at least 1.00 {ccy}")
    return f"{value:.2f}"


def major_string_to_minor(amount: str, currency: str) -> int:
    """Convert a major-unit amount string to internal minor counter."""
    try:
        value = float(Decimal(str(amount or "0").replace(",", ".")))
    except (InvalidOperation, ValueError):
        return 0
    return minor_units_for_major(value, currency)


def format_paypal_amount_value(amount: str, currency: str) -> str:
    """PayPal Orders ``purchase_units[].amount.value`` string."""
    ccy = str(currency or "").strip().upper()
    if currency_uses_whole_units(ccy):
        return str(int(Decimal(amount)))
    return f"{Decimal(amount):.2f}"
