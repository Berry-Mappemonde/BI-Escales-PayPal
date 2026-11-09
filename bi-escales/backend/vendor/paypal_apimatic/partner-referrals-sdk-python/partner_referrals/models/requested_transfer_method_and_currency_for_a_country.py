from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.transfer_method_type import TransferMethodTypeOrStr


class RequestedTransferMethodAndCurrencyForACountry(SdkBaseModel):
    """Requested transfer method and currency for a country."""

    transfer_method_type: Optional[TransferMethodTypeOrStr] = UNSET
    """Transfer Method type."""

    currencies: Optional[list[str]] = UNSET
    """Requested Currencies for a Transfer Method."""


class RequestedTransferMethodAndCurrencyForACountryDict(TypedDict):
    transfer_method_type: NotRequired[TransferMethodTypeOrStr]
    currencies: NotRequired[list[str]]
