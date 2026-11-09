from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.message4 import Message4OrStr
from .enums.name4 import Name4OrStr
from .error_details import ErrorDetails, ErrorDetailsDict
from .link_description1 import LinkDescription1, LinkDescription1Dict


class ResourceConflictError(SdkBaseModel):
    """The server has detected a conflict while processing this request."""

    name: Optional[Name4OrStr] = UNSET
    message: Optional[Message4OrStr] = UNSET
    details: Optional[list[ErrorDetails]] = UNSET
    debug_id: Optional[str] = UNSET
    """The PayPal internal ID. Used for correlation purposes."""

    links: Optional[list[LinkDescription1]] = UNSET
    """An array of request-related `HATEOAS links <https://en.wikipedia.org/wiki/HATEOAS>`__."""


class ResourceConflictErrorDict(TypedDict):
    name: NotRequired[Name4OrStr]
    message: NotRequired[Message4OrStr]
    details: NotRequired[list[ErrorDetailsDict]]
    debug_id: NotRequired[str]
    links: NotRequired[list[LinkDescription1Dict]]
