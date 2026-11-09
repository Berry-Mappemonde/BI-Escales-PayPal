from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.integration_method import IntegrationMethod, IntegrationMethodOrStr
from .enums.integration_type import IntegrationTypeOrStr
from .rest_first_party_details import RestFirstPartyDetails, RestFirstPartyDetailsDict
from .rest_third_party_details import RestThirdPartyDetails, RestThirdPartyDetailsDict


class RestApiIntegration(SdkBaseModel):
    """The integration details for PayPal REST endpoints."""

    integration_method: IntegrationMethodOrStr = IntegrationMethod.PAYPAL
    """The REST-credential integration method."""

    integration_type: IntegrationTypeOrStr
    """The type of REST-endpoint integration. To integrate with Braintree v.zero for PayPal REST endpoints, specify
    ``third_party_details``."""

    first_party_details: Optional[RestFirstPartyDetails] = UNSET
    """The integration details for PayPal first party REST endpoints."""

    third_party_details: Optional[RestThirdPartyDetails] = UNSET
    """The integration details for PayPal REST endpoints."""


class RestApiIntegrationDict(TypedDict):
    integration_method: NotRequired[IntegrationMethodOrStr]
    integration_type: IntegrationTypeOrStr
    first_party_details: NotRequired[RestFirstPartyDetailsDict]
    third_party_details: NotRequired[RestThirdPartyDetailsDict]
