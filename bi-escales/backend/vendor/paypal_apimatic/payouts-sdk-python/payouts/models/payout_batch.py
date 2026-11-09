from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .link_description import LinkDescription, LinkDescriptionDict
from .payout_batch_header import PayoutBatchHeader, PayoutBatchHeaderDict
from .payout_item1 import PayoutItem1, PayoutItem1Dict


class PayoutBatch(SdkBaseModel):
    """The PayPal-generated batch status."""

    total_items: Optional[int] = UNSET
    """The total number of items in the full result list."""

    total_pages: Optional[int] = UNSET
    """The total number of pages."""

    batch_header: Optional[PayoutBatchHeader] = UNSET
    """The payout header that is returned in response to a payout header request. Shows details for an entire payout
    request."""

    items: Optional[list[PayoutItem1]] = UNSET
    """An array of individual items."""

    links: Optional[list[LinkDescription]] = UNSET
    """An array of request-related `HATEOAS links </api/rest/responses/#hateoas-links>`__."""


class PayoutBatchDict(TypedDict):
    total_items: NotRequired[int]
    total_pages: NotRequired[int]
    batch_header: NotRequired[PayoutBatchHeaderDict]
    items: NotRequired[list[PayoutItem1Dict]]
    links: NotRequired[list[LinkDescriptionDict]]
