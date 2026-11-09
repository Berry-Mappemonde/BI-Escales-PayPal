from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .currency import Currency, CurrencyDict


class CurrencyConversionResource(SdkBaseModel):
    """The currency conversion resource."""

    from_amount: Optional[Currency] = UNSET
    """The currency and amount for a financial transaction, such as a balance or payment due."""

    to_amount: Optional[Currency] = UNSET
    """The currency and amount for a financial transaction, such as a balance or payment due."""

    exchange_rate: Optional[str] = UNSET
    """The exchange rate that is applied for this payout."""


class CurrencyConversionResourceDict(TypedDict):
    from_amount: NotRequired[CurrencyDict]
    to_amount: NotRequired[CurrencyDict]
    exchange_rate: NotRequired[str]
