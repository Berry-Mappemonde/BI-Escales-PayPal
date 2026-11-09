"""Channel3 money — single internal form: integer minor units + ISO 4217 code."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional

MoneyMinor = tuple[int, str]


def _quantize_minor(amount: Decimal) -> int:
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def minor_to_major_str(amount_minor: int) -> str:
    """Display major units with two decimals (e.g. 46995 → ``469.95``)."""
    return f"{(Decimal(int(amount_minor)) / Decimal('100')):.2f}"


def major_decimal_to_minor(value: Any) -> Optional[int]:
    try:
        amount = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if amount <= 0:
        return None
    return _quantize_minor(amount * Decimal("100"))


def parse_money_minor(raw: Any) -> Optional[MoneyMinor]:
    """Parse REST ``{price, currency}`` or UCP ``{amount, currency}`` → (minor, ISO)."""
    if raw is None or not isinstance(raw, dict):
        return None
    currency = str(raw.get("currency") or raw.get("currency_code") or "").strip().upper()
    if not currency:
        return None
    if raw.get("price") is not None:
        minor = major_decimal_to_minor(raw.get("price"))
    elif raw.get("amount") is not None:
        value = raw.get("amount")
        if isinstance(value, bool):
            return None
        try:
            minor = int(value)
        except (TypeError, ValueError):
            minor = major_decimal_to_minor(value)
        if minor is None or minor <= 0:
            return None
    elif raw.get("value") is not None:
        minor = major_decimal_to_minor(raw.get("value"))
    else:
        return None
    if minor is None or minor <= 0:
        return None
    return minor, currency


def parse_money_major(raw: Any) -> Optional[tuple[str, str]]:
    """Backward-compatible major-unit string + currency (for legacy GeoJSON props)."""
    parsed = parse_money_minor(raw)
    if not parsed:
        return None
    minor, currency = parsed
    return minor_to_major_str(minor), currency


def catalog_unit_price_minor(*, price: float, currency: str) -> MoneyMinor:
    """Seed catalogue REST prices are already in major units."""
    minor = major_decimal_to_minor(price)
    if minor is None:
        raise ValueError("invalid catalog price")
    return minor, str(currency or "").strip().upper()
