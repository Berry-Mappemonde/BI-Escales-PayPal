from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, RFC3339DateTime, SdkBaseModel
from .currency import Currency, CurrencyDict
from .enums.batch_status import BatchStatusOrStr
from .enums.funding_source import FundingSourceOrStr
from .payout_sender_batch_header import PayoutSenderBatchHeader, PayoutSenderBatchHeaderDict


class PayoutBatchHeader(SdkBaseModel):
    """The payout header that is returned in response to a payout header request. Shows details for an entire payout
    request."""

    payout_batch_id: str
    """The PayPal-generated ID for a payout."""

    batch_status: BatchStatusOrStr
    """The payouts status."""

    time_created: Optional[RFC3339DateTime] = UNSET
    """The date and time when processing for the payout began, in `Internet date and time format
    <https://tools.ietf.org/html/rfc3339#section-5.6>`__."""

    time_completed: Optional[RFC3339DateTime] = UNSET
    """The date and time when processing for the payout was completed, in `Internet date and time format
    <https://tools.ietf.org/html/rfc3339#section-5.6>`__."""

    time_closed: Optional[RFC3339DateTime] = UNSET
    """The date and time when the payout was closed, in `Internet date and time format
    <https://tools.ietf.org/html/rfc3339#section-5.6>`__. A payout is considered closed when all items in a batch are
    processed and the available balance from the temporary hold is released."""

    sender_batch_header: PayoutSenderBatchHeader
    """The sender-provided header for a payout request."""

    funding_source: Optional[FundingSourceOrStr] = UNSET
    """Identifies a funding source type."""

    amount: Optional[Currency] = UNSET
    """The currency and amount for a financial transaction, such as a balance or payment due."""

    fees: Optional[Currency] = UNSET
    """The currency and amount for a financial transaction, such as a balance or payment due."""


class PayoutBatchHeaderDict(TypedDict):
    payout_batch_id: str
    batch_status: BatchStatusOrStr
    time_created: NotRequired[RFC3339DateTime]
    time_completed: NotRequired[RFC3339DateTime]
    time_closed: NotRequired[RFC3339DateTime]
    sender_batch_header: PayoutSenderBatchHeaderDict
    funding_source: NotRequired[FundingSourceOrStr]
    amount: NotRequired[CurrencyDict]
    fees: NotRequired[CurrencyDict]
