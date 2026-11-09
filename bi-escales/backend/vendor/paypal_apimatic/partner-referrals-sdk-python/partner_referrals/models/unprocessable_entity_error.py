from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.message6 import Message6OrStr
from .enums.name6 import Name6OrStr
from .error_details import ErrorDetails, ErrorDetailsDict
from .link_description1 import LinkDescription1, LinkDescription1Dict


class UnprocessableEntityError(SdkBaseModel):
    """The requested action cannot be performed and may require interaction with APIs or processes outside of the
    current request. This is distinct from a 500 response in that there are no systemic problems limiting the API from
    performing the request."""

    name: Optional[Name6OrStr] = UNSET
    message: Optional[Message6OrStr] = UNSET
    details: Optional[list[ErrorDetails]] = UNSET
    debug_id: Optional[str] = UNSET
    """The PayPal internal ID. Used for correlation purposes."""

    links: Optional[list[LinkDescription1]] = UNSET
    """An array of request-related `HATEOAS links <https://en.wikipedia.org/wiki/HATEOAS>`__."""


class UnprocessableEntityErrorDict(TypedDict):
    name: NotRequired[Name6OrStr]
    message: NotRequired[Message6OrStr]
    details: NotRequired[list[ErrorDetailsDict]]
    debug_id: NotRequired[str]
    links: NotRequired[list[LinkDescription1Dict]]
