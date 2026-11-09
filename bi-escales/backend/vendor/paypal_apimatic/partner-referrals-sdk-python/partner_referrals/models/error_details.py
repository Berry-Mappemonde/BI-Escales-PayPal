from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.error_location import ErrorLocation, ErrorLocationOrStr


class ErrorDetails(SdkBaseModel):
    """The error details. Required for client-side ``4XX`` errors."""

    field: Optional[str] = UNSET
    """The field that caused the error. If this field is in the body, set this value to the field's JSON pointer value.
    Required for client-side errors."""

    value: Optional[str] = UNSET
    """The value of the field that caused the error."""

    location: ErrorLocationOrStr = ErrorLocation.BODY
    """The location of the field that caused the error. Value is ``body``, ``path``, or ``query``."""

    issue: str
    """The unique, fine-grained application-level error code."""

    description: Optional[str] = UNSET
    """The human-readable description for an issue. The description can change over the lifetime of an API, so clients
    must not depend on this value."""


class ErrorDetailsDict(TypedDict):
    field: NotRequired[str]
    value: NotRequired[str]
    location: NotRequired[ErrorLocationOrStr]
    issue: str
    description: NotRequired[str]
