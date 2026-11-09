from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.description4 import Description4OrStr
from .enums.issue4 import Issue4OrStr


class AuthorizationError(SdkBaseModel):
    issue: Optional[Issue4OrStr] = UNSET
    description: Optional[Description4OrStr] = UNSET


class AuthorizationErrorDict(TypedDict):
    issue: NotRequired[Issue4OrStr]
    description: NotRequired[Description4OrStr]
