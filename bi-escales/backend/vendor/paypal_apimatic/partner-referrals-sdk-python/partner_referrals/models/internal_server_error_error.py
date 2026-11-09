from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.message7 import Message7OrStr
from .enums.name7 import Name7OrStr
from .link_description1 import LinkDescription1, LinkDescription1Dict


class InternalServerErrorError(SdkBaseModel):
    """This is either a system or application error, and generally indicates that although the client appeared to
    provide a correct request, something unexpected has gone wrong on the server."""

    name: Optional[Name7OrStr] = UNSET
    message: Optional[Message7OrStr] = UNSET
    debug_id: Optional[str] = UNSET
    """The PayPal internal ID. Used for correlation purposes."""

    links: Optional[list[LinkDescription1]] = UNSET
    """An array of request-related `HATEOAS links <https://en.wikipedia.org/wiki/HATEOAS>`__."""


class InternalServerErrorErrorDict(TypedDict):
    name: NotRequired[Name7OrStr]
    message: NotRequired[Message7OrStr]
    debug_id: NotRequired[str]
    links: NotRequired[list[LinkDescription1Dict]]
