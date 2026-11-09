from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .authorization_error import AuthorizationError, AuthorizationErrorDict


class M401(SdkBaseModel):
    details: Optional[list[AuthorizationError]] = UNSET


class M401Dict(TypedDict):
    details: NotRequired[list[AuthorizationErrorDict]]
