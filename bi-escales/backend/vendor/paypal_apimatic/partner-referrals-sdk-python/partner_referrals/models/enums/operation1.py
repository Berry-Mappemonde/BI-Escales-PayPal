from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Operation1(str, Enum):
    """The operation to enable for the customer. To enable the collection of the API permissions that you require to
    integrate with the customer, specify ``API_INTEGRATION``. ``BANK_ADDITION`` is supported only for the US."""

    API_INTEGRATION = "API_INTEGRATION"
    BANK_ADDITION = "BANK_ADDITION"
    BILLING_AGREEMENT = "BILLING_AGREEMENT"
    CONTEXTUAL_MARKETING_CONSENT = "CONTEXTUAL_MARKETING_CONSENT"
    OFFLINE_ONBOARDING = "OFFLINE_ONBOARDING"
    SALESFORCE_REFERRAL = "SALESFORCE_REFERRAL"

    __str__ = str.__str__


Operation1OrStr: TypeAlias = Annotated[Operation1 | str, open_enum_validator(Operation1)]
