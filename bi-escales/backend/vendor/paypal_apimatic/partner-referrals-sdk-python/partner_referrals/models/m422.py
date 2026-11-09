from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .unions.detail1 import Detail1, Detail1Dict


class M422(SdkBaseModel):
    details: Optional[list[Detail1]] = UNSET


class M422Dict(TypedDict):
    details: NotRequired[list[Detail1Dict]]
