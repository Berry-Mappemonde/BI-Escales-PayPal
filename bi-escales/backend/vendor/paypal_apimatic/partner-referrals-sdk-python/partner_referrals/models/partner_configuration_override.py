from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel


class PartnerConfigurationOverride(SdkBaseModel):
    """The preference to customize the web experience of the customer by overriding that is set at the Partner's
    Account."""

    return_url: Optional[str] = UNSET
    """The URL to which to redirect the customer upon completion of the onboarding process."""

    return_url_description: Optional[str] = UNSET
    """The description of the return URL."""

    show_add_credit_card: Optional[bool] = UNSET
    """Indicates whether to show an add credit card page."""


class PartnerConfigurationOverrideDict(TypedDict):
    return_url: NotRequired[str]
    return_url_description: NotRequired[str]
    show_add_credit_card: NotRequired[bool]
