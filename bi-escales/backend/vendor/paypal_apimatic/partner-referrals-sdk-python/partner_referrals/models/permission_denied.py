from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.description5 import Description5OrStr
from .enums.issue5 import Issue5OrStr


class PermissionDenied(SdkBaseModel):
    issue: Optional[Issue5OrStr] = UNSET
    description: Optional[Description5OrStr] = UNSET


class PermissionDeniedDict(TypedDict):
    issue: NotRequired[Issue5OrStr]
    description: NotRequired[Description5OrStr]
