from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .bank_account import BankAccount, BankAccountDict


class FinancialInstrument(SdkBaseModel):
    """Financial instruments attached to this account."""

    banks: Optional[list[BankAccount]] = UNSET
    """An array of banks attached to this managed account."""


class FinancialInstrumentDict(TypedDict):
    banks: NotRequired[list[BankAccountDict]]
