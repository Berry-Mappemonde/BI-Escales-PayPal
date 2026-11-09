from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.issue7 import Issue7OrStr


class AccountStatusError(SdkBaseModel):
    issue: Optional[Issue7OrStr] = UNSET
    description: Optional[str] = UNSET


class AccountStatusErrorDict(TypedDict):
    issue: NotRequired[Issue7OrStr]
    description: NotRequired[str]
