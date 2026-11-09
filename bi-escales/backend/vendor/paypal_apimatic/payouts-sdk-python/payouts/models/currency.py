from __future__ import annotations

from typing_extensions import TypedDict

from ..core import SdkBaseModel


class Currency(SdkBaseModel):
    """The currency and amount for a financial transaction, such as a balance or payment due."""

    currency: str
    """The `three-character ISO-4217 currency code </docs/integration/direct/rest/currency-codes/>`__."""

    value: str
    """The value, which might be:<ul><li>An integer for currencies like ``JPY`` that are not typically
    fractional.</li><li>A decimal fraction for currencies like ``TND`` that are subdivided into
    thousandths.</li></ul>For the required number of decimal places for a currency code, see `Currency codes - ISO 4217
    <https://www.iso.org/iso-4217-currency-codes.html>`__."""


class CurrencyDict(TypedDict):
    currency: str
    value: str
