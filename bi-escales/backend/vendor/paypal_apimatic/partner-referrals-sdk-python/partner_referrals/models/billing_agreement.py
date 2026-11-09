from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .billing_experience_preference import BillingExperiencePreference, BillingExperiencePreferenceDict


class BillingAgreement(SdkBaseModel):
    """The details of the billing agreement between the partner and a seller."""

    description: Optional[str] = UNSET
    """The billing agreement description."""

    billing_experience_preference: Optional[BillingExperiencePreference] = UNSET
    """The preference that customizes the billing experience of the customer."""

    merchant_custom_data: Optional[str] = UNSET
    """The custom data for the billing agreement."""

    approval_url: Optional[str] = UNSET
    """The URL to which to redirect seller to accept the billing agreement."""

    ec_token: Optional[str] = UNSET
    """The billing agreement token for the agreement."""


class BillingAgreementDict(TypedDict):
    description: NotRequired[str]
    billing_experience_preference: NotRequired[BillingExperiencePreferenceDict]
    merchant_custom_data: NotRequired[str]
    approval_url: NotRequired[str]
    ec_token: NotRequired[str]
