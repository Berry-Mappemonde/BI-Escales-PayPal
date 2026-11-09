from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.message6 import Message6OrStr
from .enums.name6 import Name6OrStr
from .error_details4 import ErrorDetails4, ErrorDetails4Dict
from .link_description1 import LinkDescription1, LinkDescription1Dict


class V2CustomerPartnerReferrals422Error1(SdkBaseModel):
    name: Optional[Name6OrStr] = UNSET
    message: Optional[Message6OrStr] = UNSET
    details: Optional[list[ErrorDetails4]] = UNSET
    debug_id: Optional[str] = UNSET
    """The PayPal internal ID. Used for correlation purposes."""

    links: Optional[list[LinkDescription1]] = UNSET
    """An array of request-related `HATEOAS links <https://en.wikipedia.org/wiki/HATEOAS>`__."""


class V2CustomerPartnerReferrals422Error1Dict(TypedDict):
    name: NotRequired[Name6OrStr]
    message: NotRequired[Message6OrStr]
    details: NotRequired[list[ErrorDetails4Dict]]
    debug_id: NotRequired[str]
    links: NotRequired[list[LinkDescription1Dict]]
