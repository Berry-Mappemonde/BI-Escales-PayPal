from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.message1 import Message1OrStr
from .enums.name1 import Name1OrStr
from .error_details2 import ErrorDetails2, ErrorDetails2Dict
from .link_description1 import LinkDescription1, LinkDescription1Dict


class V2CustomerPartnerReferrals401Error1(SdkBaseModel):
    name: Optional[Name1OrStr] = UNSET
    message: Optional[Message1OrStr] = UNSET
    details: Optional[list[ErrorDetails2]] = UNSET
    debug_id: Optional[str] = UNSET
    """The PayPal internal ID. Used for correlation purposes."""

    links: Optional[list[LinkDescription1]] = UNSET
    """An array of request-related `HATEOAS links <https://en.wikipedia.org/wiki/HATEOAS>`__."""


class V2CustomerPartnerReferrals401Error1Dict(TypedDict):
    name: NotRequired[Name1OrStr]
    message: NotRequired[Message1OrStr]
    details: NotRequired[list[ErrorDetails2Dict]]
    debug_id: NotRequired[str]
    links: NotRequired[list[LinkDescription1Dict]]
