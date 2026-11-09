from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.description6 import Description6OrStr
from .enums.issue6 import Issue6OrStr


class UserNotFound(SdkBaseModel):
    issue: Optional[Issue6OrStr] = UNSET
    description: Optional[Description6OrStr] = UNSET


class UserNotFoundDict(TypedDict):
    issue: NotRequired[Issue6OrStr]
    description: NotRequired[Description6OrStr]
