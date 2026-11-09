from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .requested_transfer_method_and_currency_for_a_country import (
    RequestedTransferMethodAndCurrencyForACountry,
    RequestedTransferMethodAndCurrencyForACountryDict,
)


class RequestedCountryTransferMethodAndCurrency(SdkBaseModel):
    """Requested country, transfer method and currency."""

    country: Optional[str] = UNSET
    """The `two-character ISO 3166-1 code </docs/api/reference/country-codes/>`__ that identifies the country or
    region.<blockquote><strong>Note:</strong> The country code for Great Britain is <code>GB</code> and not
    <code>UK</code> as used in the top-level domain names for that country. Use the ``C2`` country code for China
    worldwide for comparable uncontrolled price (CUP) method, bank card, and cross-border transactions.</blockquote>"""

    transfer_methods: Optional[list[RequestedTransferMethodAndCurrencyForACountry]] = UNSET
    """Requested transfer method and currency for a country."""


class RequestedCountryTransferMethodAndCurrencyDict(TypedDict):
    country: NotRequired[str]
    transfer_methods: NotRequired[list[RequestedTransferMethodAndCurrencyForACountryDict]]
