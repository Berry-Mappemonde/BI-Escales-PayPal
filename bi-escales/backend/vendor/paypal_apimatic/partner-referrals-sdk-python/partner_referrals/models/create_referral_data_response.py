from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .link_description import LinkDescription, LinkDescriptionDict


class CreateReferralDataResponse(SdkBaseModel):
    """The shared referral data."""

    links: Optional[list[LinkDescription]] = UNSET
    """An array of request-related `HATEOAS links </docs/api/overview/#hateoas-links>`__."""


class CreateReferralDataResponseDict(TypedDict):
    links: NotRequired[list[LinkDescriptionDict]]
