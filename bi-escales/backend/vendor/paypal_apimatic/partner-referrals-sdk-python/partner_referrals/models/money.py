from __future__ import annotations

from typing_extensions import TypedDict

from ..core import SdkBaseModel


class Money(SdkBaseModel):
    """The currency and amount for a financial transaction, such as a balance or payment due."""

    currency_code: str
    """The `three-character ISO-4217 currency code </docs/integration/direct/rest/currency-codes/>`__ that identifies
    the currency."""

    value: str
    """The value, which might be:<ul><li>An integer for currencies like ``JPY`` that are not typically
    fractional.</li><li>A decimal fraction for currencies like ``TND`` that are subdivided into
    thousandths.</li></ul>For the required number of decimal places for a currency code, see `Currency Codes
    </docs/integration/direct/rest/currency-codes/>`__."""


class MoneyDict(TypedDict):
    currency_code: str
    value: str
