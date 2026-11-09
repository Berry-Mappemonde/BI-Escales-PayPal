from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .error_details import ErrorDetails, ErrorDetailsDict
from .link_description import LinkDescription, LinkDescriptionDict


class ErrorError(SdkBaseModel):
    """The error details."""

    name: str
    """The human-readable, unique name of the error."""

    message: str
    """The message that describes the error."""

    debug_id: str
    """The PayPal internal ID. Used for correlation purposes."""

    information_link: Optional[str] = UNSET
    """The information link, or URI, that shows detailed information about this error for the developer."""

    details: Optional[list[ErrorDetails]] = UNSET
    """An array of additional details about the error."""

    links: Optional[list[LinkDescription]] = UNSET
    """An array of request-related `HATEOAS links </docs/api/reference/api-responses/#hateoas-links>`__."""


class ErrorErrorDict(TypedDict):
    name: str
    message: str
    debug_id: str
    information_link: NotRequired[str]
    details: NotRequired[list[ErrorDetailsDict]]
    links: NotRequired[list[LinkDescriptionDict]]
