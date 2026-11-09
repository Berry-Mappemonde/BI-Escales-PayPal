from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.message3 import Message3OrStr
from .enums.name3 import Name3OrStr
from .error_details1 import ErrorDetails1, ErrorDetails1Dict
from .link_description1 import LinkDescription1, LinkDescription1Dict


class NotFoundError(SdkBaseModel):
    """The server has not found anything matching the request URI. This either means that the URI is incorrect or the
    resource is not available."""

    name: Optional[Name3OrStr] = UNSET
    message: Optional[Message3OrStr] = UNSET
    details: Optional[list[ErrorDetails1]] = UNSET
    debug_id: Optional[str] = UNSET
    """The PayPal internal ID. Used for correlation purposes."""

    links: Optional[list[LinkDescription1]] = UNSET
    """An array of request-related `HATEOAS links <https://en.wikipedia.org/wiki/HATEOAS>`__."""


class NotFoundErrorDict(TypedDict):
    name: NotRequired[Name3OrStr]
    message: NotRequired[Message3OrStr]
    details: NotRequired[list[ErrorDetails1Dict]]
    debug_id: NotRequired[str]
    links: NotRequired[list[LinkDescription1Dict]]
