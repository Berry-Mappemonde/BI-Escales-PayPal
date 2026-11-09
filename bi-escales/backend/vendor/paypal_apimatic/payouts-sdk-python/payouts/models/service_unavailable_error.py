from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.message8 import Message8OrStr
from .enums.name8 import Name8OrStr
from .link_description1 import LinkDescription1, LinkDescription1Dict


class ServiceUnavailableError(SdkBaseModel):
    """The server is temporarily unable to handle the request, for example, because of planned maintenance or
    downtime."""

    name: Optional[Name8OrStr] = UNSET
    message: Optional[Message8OrStr] = UNSET
    debug_id: Optional[str] = UNSET
    """The PayPal internal ID. Used for correlation purposes."""

    links: Optional[list[LinkDescription1]] = UNSET
    """An array of request-related `HATEOAS links <https://en.wikipedia.org/wiki/HATEOAS>`__."""


class ServiceUnavailableErrorDict(TypedDict):
    name: NotRequired[Name8OrStr]
    message: NotRequired[Message8OrStr]
    debug_id: NotRequired[str]
    links: NotRequired[list[LinkDescription1Dict]]
