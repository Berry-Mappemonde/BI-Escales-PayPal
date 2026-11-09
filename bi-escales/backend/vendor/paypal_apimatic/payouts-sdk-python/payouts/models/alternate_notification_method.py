from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .phone import Phone, PhoneDict


class AlternateNotificationMethod(SdkBaseModel):
    """Captures additional notification modes to reach out to the receiver regarding this payment."""

    phone: Optional[Phone] = UNSET
    """The phone number in its canonical international `E.164 numbering plan format
    <https://www.itu.int/rec/T-REC-E.164/en>`__."""


class AlternateNotificationMethodDict(TypedDict):
    phone: NotRequired[PhoneDict]
