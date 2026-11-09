from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.description1 import Description1OrStr
from .enums.issue1 import Issue1OrStr


class InvalidParameterSyntax(SdkBaseModel):
    issue: Optional[Issue1OrStr] = UNSET
    description: Optional[Description1OrStr] = UNSET


class InvalidParameterSyntaxDict(TypedDict):
    issue: NotRequired[Issue1OrStr]
    description: NotRequired[Description1OrStr]
