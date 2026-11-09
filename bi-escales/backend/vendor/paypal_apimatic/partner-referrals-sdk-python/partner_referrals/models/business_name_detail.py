from __future__ import annotations

from pydantic import Field
from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.the_business_name_type import TheBusinessNameTypeOrStr


class BusinessNameDetail(SdkBaseModel):
    business_name: Optional[str] = UNSET
    """Required. The business name of the party."""

    type_: TheBusinessNameTypeOrStr = Field(alias="type")
    """Business name type"""


class BusinessNameDetailDict(TypedDict):
    business_name: NotRequired[str]
    type_: TheBusinessNameTypeOrStr
