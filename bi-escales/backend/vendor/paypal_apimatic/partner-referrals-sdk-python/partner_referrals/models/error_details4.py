from __future__ import annotations

from typing import Literal

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.description11 import Description11OrStr
from .enums.error_location import ErrorLocation, ErrorLocationOrStr


class ErrorDetails4(SdkBaseModel):
    """The error details. Required for client-side ``4XX`` errors."""

    field: Optional[str] = UNSET
    """The field that caused the error. If this field is in the body, set this value to the field's JSON pointer value.
    Required for client-side errors."""

    value: Optional[str] = UNSET
    """The value of the field that caused the error."""

    location: ErrorLocationOrStr = ErrorLocation.BODY
    """The location of the field that caused the error. Value is ``body``, ``path``, or ``query``."""

    issue: Literal["USER_NOT_FOUND"] = "USER_NOT_FOUND"
    """The unique, fine-grained application-level error code."""

    description: Optional[Description11OrStr] = UNSET
    """The human-readable description for an issue. The description can change over the lifetime of an API, so clients
    must not depend on this value."""


class ErrorDetails4Dict(TypedDict):
    field: NotRequired[str]
    value: NotRequired[str]
    location: NotRequired[ErrorLocationOrStr]
    issue: Literal["USER_NOT_FOUND"]
    description: NotRequired[Description11OrStr]
