from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .money import Money, MoneyDict


class CurrencyRange(SdkBaseModel):
    """The currency range, from the minimum inclusive amount to the maximum inclusive amount."""

    minimum_amount: Optional[Money] = UNSET
    """The currency and amount for a financial transaction, such as a balance or payment due."""

    maximum_amount: Optional[Money] = UNSET
    """The currency and amount for a financial transaction, such as a balance or payment due."""


class CurrencyRangeDict(TypedDict):
    minimum_amount: NotRequired[MoneyDict]
    maximum_amount: NotRequired[MoneyDict]
