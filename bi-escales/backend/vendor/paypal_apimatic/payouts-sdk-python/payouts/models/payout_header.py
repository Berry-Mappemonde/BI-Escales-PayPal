from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, RFC3339DateTime, SdkBaseModel
from .enums.batch_status import BatchStatusOrStr
from .payout_sender_batch_header import PayoutSenderBatchHeader, PayoutSenderBatchHeaderDict


class PayoutHeader(SdkBaseModel):
    """The payout header that is returned in response to a payout header request. Shows details for an entire payout
    request."""

    payout_batch_id: str
    """The PayPal-generated ID for a payout."""

    batch_status: BatchStatusOrStr
    """The payouts status."""

    time_created: Optional[RFC3339DateTime] = UNSET
    """The date and time when processing for the payout began, in `Internet date and time format
    <https://tools.ietf.org/html/rfc3339#section-5.6>`__."""

    sender_batch_header: PayoutSenderBatchHeader
    """The sender-provided header for a payout request."""


class PayoutHeaderDict(TypedDict):
    payout_batch_id: str
    batch_status: BatchStatusOrStr
    time_created: NotRequired[RFC3339DateTime]
    sender_batch_header: PayoutSenderBatchHeaderDict
