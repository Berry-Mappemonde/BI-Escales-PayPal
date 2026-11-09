from __future__ import annotations

from typing import Literal

from pydantic import Field
from typing_extensions import TypedDict

from ..core import SdkBaseModel


class LegalConsent(SdkBaseModel):
    """The customer-provided consent."""

    type_: Literal["SHARE_DATA_CONSENT"] = Field(default="SHARE_DATA_CONSENT", alias="type")
    """The type of consent. ``SHARE_DATA_CONSENT`` gives consent to you to share your customer's data with PayPal."""

    granted: bool
    """Indicates whether the customer agreed to share this type of data. To give consent, specify ``true``. To withhold
    consent, specify ``false``."""


class LegalConsentDict(TypedDict):
    type_: Literal["SHARE_DATA_CONSENT"]
    granted: bool
