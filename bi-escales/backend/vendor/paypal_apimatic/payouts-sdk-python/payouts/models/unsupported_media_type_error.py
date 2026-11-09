from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.message5 import Message5OrStr
from .enums.name5 import Name5OrStr
from .error_details1 import ErrorDetails1, ErrorDetails1Dict
from .link_description1 import LinkDescription1, LinkDescription1Dict


class UnsupportedMediaTypeError(SdkBaseModel):
    """The server does not support the request payload's media type."""

    name: Optional[Name5OrStr] = UNSET
    message: Optional[Message5OrStr] = UNSET
    details: Optional[list[ErrorDetails1]] = UNSET
    debug_id: Optional[str] = UNSET
    """The PayPal internal ID. Used for correlation purposes."""

    links: Optional[list[LinkDescription1]] = UNSET
    """An array of request-related `HATEOAS links <https://en.wikipedia.org/wiki/HATEOAS>`__."""


class UnsupportedMediaTypeErrorDict(TypedDict):
    name: NotRequired[Name5OrStr]
    message: NotRequired[Message5OrStr]
    details: NotRequired[list[ErrorDetails1Dict]]
    debug_id: NotRequired[str]
    links: NotRequired[list[LinkDescription1Dict]]
