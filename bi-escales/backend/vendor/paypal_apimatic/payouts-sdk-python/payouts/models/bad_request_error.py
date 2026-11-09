from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.message import MessageOrStr
from .enums.name10 import Name10OrStr
from .error_details1 import ErrorDetails1, ErrorDetails1Dict
from .link_description1 import LinkDescription1, LinkDescription1Dict


class BadRequestError(SdkBaseModel):
    """Request is not well-formed, syntactically incorrect, or violates schema."""

    name: Optional[Name10OrStr] = UNSET
    message: Optional[MessageOrStr] = UNSET
    details: Optional[list[ErrorDetails1]] = UNSET
    debug_id: Optional[str] = UNSET
    """The PayPal internal ID. Used for correlation purposes."""

    links: Optional[list[LinkDescription1]] = UNSET
    """An array of request-related `HATEOAS links <https://en.wikipedia.org/wiki/HATEOAS>`__."""


class BadRequestErrorDict(TypedDict):
    name: NotRequired[Name10OrStr]
    message: NotRequired[MessageOrStr]
    details: NotRequired[list[ErrorDetails1Dict]]
    debug_id: NotRequired[str]
    links: NotRequired[list[LinkDescription1Dict]]
