from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.message1 import Message1OrStr
from .enums.name1 import Name1OrStr
from .error_details import ErrorDetails, ErrorDetailsDict
from .link_description1 import LinkDescription1, LinkDescription1Dict


class UnauthorizedError(SdkBaseModel):
    """Authentication failed due to missing Authorization header, or invalid authentication credentials."""

    name: Optional[Name1OrStr] = UNSET
    message: Optional[Message1OrStr] = UNSET
    details: Optional[list[ErrorDetails]] = UNSET
    debug_id: Optional[str] = UNSET
    """The PayPal internal ID. Used for correlation purposes."""

    links: Optional[list[LinkDescription1]] = UNSET
    """An array of request-related `HATEOAS links <https://en.wikipedia.org/wiki/HATEOAS>`__."""


class UnauthorizedErrorDict(TypedDict):
    name: NotRequired[Name1OrStr]
    message: NotRequired[Message1OrStr]
    details: NotRequired[list[ErrorDetailsDict]]
    debug_id: NotRequired[str]
    links: NotRequired[list[LinkDescription1Dict]]
