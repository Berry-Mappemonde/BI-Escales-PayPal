from __future__ import annotations

from typing_extensions import TypedDict

from ..core import SdkBaseModel
from .payout_item import PayoutItem, PayoutItemDict
from .sender_batch_header import SenderBatchHeader, SenderBatchHeaderDict


class CreatePayoutRequest(SdkBaseModel):
    """The create payout request."""

    sender_batch_header: SenderBatchHeader
    """The sender-provided payout header for a payout request."""

    items: list[PayoutItem]
    """An array of individual payout items."""


class CreatePayoutRequestDict(TypedDict):
    sender_batch_header: SenderBatchHeaderDict
    items: list[PayoutItemDict]
