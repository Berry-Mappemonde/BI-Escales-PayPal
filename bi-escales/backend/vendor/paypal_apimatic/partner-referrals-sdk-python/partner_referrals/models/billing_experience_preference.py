from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel


class BillingExperiencePreference(SdkBaseModel):
    """The preference that customizes the billing experience of the customer."""

    experience_id: Optional[str] = UNSET
    """The ID of the payment web experience profile."""

    billing_context_set: Optional[bool] = UNSET
    """Indicates whether the partner has already displayed the billing context to the seller."""


class BillingExperiencePreferenceDict(TypedDict):
    experience_id: NotRequired[str]
    billing_context_set: NotRequired[bool]
