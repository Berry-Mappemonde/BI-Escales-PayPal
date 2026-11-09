from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .link_description import LinkDescription, LinkDescriptionDict
from .payout_header import PayoutHeader, PayoutHeaderDict


class CreatePayoutResponse(SdkBaseModel):
    """The create payout response."""

    batch_header: Optional[PayoutHeader] = UNSET
    """The payout header that is returned in response to a payout header request. Shows details for an entire payout
    request."""

    links: Optional[list[LinkDescription]] = UNSET
    """An array of request-related `HATEOAS links </api/rest/responses/#hateoas-links>`__."""


class CreatePayoutResponseDict(TypedDict):
    batch_header: NotRequired[PayoutHeaderDict]
    links: NotRequired[list[LinkDescriptionDict]]
