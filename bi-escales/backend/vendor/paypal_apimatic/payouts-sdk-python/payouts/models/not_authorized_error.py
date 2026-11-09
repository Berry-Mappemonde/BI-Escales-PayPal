from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.message2 import Message2OrStr
from .enums.name2 import Name2OrStr
from .error_details1 import ErrorDetails1, ErrorDetails1Dict
from .link_description1 import LinkDescription1, LinkDescription1Dict


class NotAuthorizedError(SdkBaseModel):
    """The client is not authorized to access this resource, although it may have valid credentials."""

    name: Optional[Name2OrStr] = UNSET
    message: Optional[Message2OrStr] = UNSET
    details: Optional[list[ErrorDetails1]] = UNSET
    debug_id: Optional[str] = UNSET
    """The PayPal internal ID. Used for correlation purposes."""

    links: Optional[list[LinkDescription1]] = UNSET
    """An array of request-related `HATEOAS links <https://en.wikipedia.org/wiki/HATEOAS>`__."""


class NotAuthorizedErrorDict(TypedDict):
    name: NotRequired[Name2OrStr]
    message: NotRequired[Message2OrStr]
    details: NotRequired[list[ErrorDetails1Dict]]
    debug_id: NotRequired[str]
    links: NotRequired[list[LinkDescription1Dict]]
