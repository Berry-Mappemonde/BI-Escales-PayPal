from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.description import DescriptionOrStr
from .enums.issue import IssueOrStr


class InvalidStringLength(SdkBaseModel):
    issue: Optional[IssueOrStr] = UNSET
    description: Optional[DescriptionOrStr] = UNSET


class InvalidStringLengthDict(TypedDict):
    issue: NotRequired[IssueOrStr]
    description: NotRequired[DescriptionOrStr]
