from __future__ import annotations

from typing import Any

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .rest_api_integration import RestApiIntegration, RestApiIntegrationDict


class IntegrationDetails(SdkBaseModel):
    """The integration details for the partner and customer relationship. Required if ``operation`` is
    ``API_INTEGRATION``."""

    classic_api_integration: Optional[Any] = UNSET
    """The integration details for PayPal CLASSIC endpoints."""

    rest_api_integration: Optional[RestApiIntegration] = UNSET
    """The integration details for PayPal REST endpoints."""


class IntegrationDetailsDict(TypedDict):
    classic_api_integration: NotRequired[Any]
    rest_api_integration: NotRequired[RestApiIntegrationDict]
