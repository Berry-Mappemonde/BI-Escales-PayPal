from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel


class BusinessName(SdkBaseModel):
    """The business name of the party."""

    business_name: Optional[str] = UNSET
    """Required. The business name of the party."""


class BusinessNameDict(TypedDict):
    business_name: NotRequired[str]
