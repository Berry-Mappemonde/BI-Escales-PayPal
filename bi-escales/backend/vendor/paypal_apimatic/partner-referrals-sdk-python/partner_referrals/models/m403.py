from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .permission_denied import PermissionDenied, PermissionDeniedDict


class M403(SdkBaseModel):
    details: Optional[list[PermissionDenied]] = UNSET


class M403Dict(TypedDict):
    details: NotRequired[list[PermissionDeniedDict]]
