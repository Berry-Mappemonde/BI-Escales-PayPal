from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .unions.detail import Detail, DetailDict


class M400(SdkBaseModel):
    details: Optional[list[Detail]] = UNSET


class M400Dict(TypedDict):
    details: NotRequired[list[DetailDict]]
