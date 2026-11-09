from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.description2 import Description2OrStr
from .enums.issue2 import Issue2OrStr


class InvalidParameterValue(SdkBaseModel):
    issue: Optional[Issue2OrStr] = UNSET
    description: Optional[Description2OrStr] = UNSET


class InvalidParameterValueDict(TypedDict):
    issue: NotRequired[Issue2OrStr]
    description: NotRequired[Description2OrStr]
