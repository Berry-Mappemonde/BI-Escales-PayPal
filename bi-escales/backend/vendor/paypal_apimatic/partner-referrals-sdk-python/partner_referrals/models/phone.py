from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel


class Phone(SdkBaseModel):
    """The phone number in its canonical international `E.164 numbering plan format
    <https://www.itu.int/rec/T-REC-E.164/en>`__."""

    country_code: str
    """The country calling code (CC), in its canonical international `E.164 numbering plan format
    <https://www.itu.int/rec/T-REC-E.164/en>`__. The combined length of the CC and the national number must not be
    greater than 15 digits. The national number consists of a national destination code (NDC) and subscriber number
    (SN)."""

    national_number: str
    """The national number, in its canonical international `E.164 numbering plan format
    <https://www.itu.int/rec/T-REC-E.164/en>`__. The combined length of the country calling code (CC) and the national
    number must not be greater than 15 digits. The national number consists of a national destination code (NDC) and
    subscriber number (SN)."""

    extension_number: Optional[str] = UNSET
    """The extension number."""


class PhoneDict(TypedDict):
    country_code: str
    national_number: str
    extension_number: NotRequired[str]
