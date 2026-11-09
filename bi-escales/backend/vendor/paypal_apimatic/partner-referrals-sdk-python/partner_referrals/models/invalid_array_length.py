from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.description3 import Description3OrStr
from .enums.issue3 import Issue3OrStr


class InvalidArrayLength(SdkBaseModel):
    issue: Optional[Issue3OrStr] = UNSET
    description: Optional[Description3OrStr] = UNSET


class InvalidArrayLengthDict(TypedDict):
    issue: NotRequired[Issue3OrStr]
    description: NotRequired[Description3OrStr]
