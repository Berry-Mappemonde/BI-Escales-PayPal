from __future__ import annotations

from typing_extensions import TypedDict

from ..core import SdkBaseModel


class Mandate(SdkBaseModel):
    """Seller’s consent to operate on this financial instrument."""

    accepted: bool
    """Whether mandate was accepted or not."""


class MandateDict(TypedDict):
    accepted: bool
