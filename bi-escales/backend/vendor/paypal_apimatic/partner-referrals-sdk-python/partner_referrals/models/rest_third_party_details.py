from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.rest_endpoint_features import RestEndpointFeaturesOrStr
from .enums.signup_mode import SignupModeOrStr


class RestThirdPartyDetails(SdkBaseModel):
    """The integration details for PayPal REST endpoints."""

    features: Optional[list[RestEndpointFeaturesOrStr]] = UNSET
    """An array of features that partner can access, or use, in PayPal on behalf of the seller. The seller grants
    permission for these features to the partner."""

    signup_mode: Optional[SignupModeOrStr] = UNSET
    """Signup Mode to be used for sellers for third party integration."""

    organization: Optional[str] = UNSET
    """The organization to which the account will belong in the partner’s hierarchy, as a path."""


class RestThirdPartyDetailsDict(TypedDict):
    features: NotRequired[list[RestEndpointFeaturesOrStr]]
    signup_mode: NotRequired[SignupModeOrStr]
    organization: NotRequired[str]
