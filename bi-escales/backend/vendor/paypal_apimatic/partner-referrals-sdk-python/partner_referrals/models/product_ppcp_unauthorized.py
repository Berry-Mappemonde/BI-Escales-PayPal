from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.description7 import Description7OrStr
from .enums.issue8 import Issue8OrStr


class ProductPpcpUnauthorized(SdkBaseModel):
    issue: Optional[Issue8OrStr] = UNSET
    description: Optional[Description7OrStr] = UNSET


class ProductPpcpUnauthorizedDict(TypedDict):
    issue: NotRequired[Issue8OrStr]
    description: NotRequired[Description7OrStr]
