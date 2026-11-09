from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.message2 import Message2OrStr
from .enums.name2 import Name2OrStr
from .error_details3 import ErrorDetails3, ErrorDetails3Dict
from .link_description1 import LinkDescription1, LinkDescription1Dict


class V2CustomerPartnerReferrals403Error(SdkBaseModel):
    name: Optional[Name2OrStr] = UNSET
    message: Optional[Message2OrStr] = UNSET
    details: Optional[list[ErrorDetails3]] = UNSET
    debug_id: Optional[str] = UNSET
    """The PayPal internal ID. Used for correlation purposes."""

    links: Optional[list[LinkDescription1]] = UNSET
    """An array of request-related `HATEOAS links <https://en.wikipedia.org/wiki/HATEOAS>`__."""


class V2CustomerPartnerReferrals403ErrorDict(TypedDict):
    name: NotRequired[Name2OrStr]
    message: NotRequired[Message2OrStr]
    details: NotRequired[list[ErrorDetails3Dict]]
    debug_id: NotRequired[str]
    links: NotRequired[list[LinkDescription1Dict]]
