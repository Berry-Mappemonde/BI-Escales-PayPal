from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .requested_country_transfer_method_and_currency import (
    RequestedCountryTransferMethodAndCurrency,
    RequestedCountryTransferMethodAndCurrencyDict,
)


class PayoutAttributes(SdkBaseModel):
    """Payout specific attributes."""

    marketplace: Optional[bool] = UNSET
    """If ``true``, specifies that the merchant or platform is offering goods or services on behalf of 3rd party
    sellers."""

    kyc_required: Optional[bool] = UNSET
    """If ``true``, specifies that the Kyc is required for the merchant."""

    country_transfer_method_currency_selection: Optional[list[RequestedCountryTransferMethodAndCurrency]] = UNSET
    """Requested country, transfer method and currency."""


class PayoutAttributesDict(TypedDict):
    marketplace: NotRequired[bool]
    kyc_required: NotRequired[bool]
    country_transfer_method_currency_selection: NotRequired[list[RequestedCountryTransferMethodAndCurrencyDict]]
