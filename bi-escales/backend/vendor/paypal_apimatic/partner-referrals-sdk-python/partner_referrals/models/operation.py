from __future__ import annotations

from typing import Any

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .billing_agreement import BillingAgreement, BillingAgreementDict
from .enums.operation1 import Operation1OrStr
from .integration_details import IntegrationDetails, IntegrationDetailsDict


class Operation(SdkBaseModel):
    """The required operation to share data."""

    operation: Operation1OrStr
    """The operation to enable for the customer. To enable the collection of the API permissions that you require to
    integrate with the customer, specify ``API_INTEGRATION``. ``BANK_ADDITION`` is supported only for the US."""

    api_integration_preference: Optional[IntegrationDetails] = UNSET
    """The integration details for the partner and customer relationship. Required if ``operation`` is
    ``API_INTEGRATION``."""

    offline_onboarding_preference: Optional[Any] = UNSET
    """The preference details for offline onboarding without UI."""

    billing_agreement: Optional[BillingAgreement] = UNSET
    """The details of the billing agreement between the partner and a seller."""


class OperationDict(TypedDict):
    operation: Operation1OrStr
    api_integration_preference: NotRequired[IntegrationDetailsDict]
    offline_onboarding_preference: NotRequired[Any]
    billing_agreement: NotRequired[BillingAgreementDict]
