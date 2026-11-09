from __future__ import annotations

from pydantic import Field
from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.business_type import BusinessTypeOrStr
from .enums.the_business_sub_type import TheBusinessSubTypeOrStr


class BusinessTypeInformation(SdkBaseModel):
    """The type and subtype of the business."""

    type_: Optional[BusinessTypeOrStr] = Field(default=UNSET, alias="type")
    """The business types classified"""

    subtype: Optional[TheBusinessSubTypeOrStr] = UNSET
    """Sub classification of the business type"""


class BusinessTypeInformationDict(TypedDict):
    type_: NotRequired[BusinessTypeOrStr]
    subtype: NotRequired[TheBusinessSubTypeOrStr]
