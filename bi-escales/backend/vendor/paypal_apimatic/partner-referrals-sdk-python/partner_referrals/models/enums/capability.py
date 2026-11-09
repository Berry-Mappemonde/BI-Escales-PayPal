from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Capability(str, Enum):
    """Optional capabilities of the selected PayPal product for which the customer is being onboarded."""

    PAYPAL_WALLET_VAULTING_ADVANCED = "PAYPAL_WALLET_VAULTING_ADVANCED"
    PAY_UPON_INVOICE = "PAY_UPON_INVOICE"
    APPLE_PAY = "APPLE_PAY"
    GOOGLE_PAY = "GOOGLE_PAY"

    __str__ = str.__str__


CapabilityOrStr: TypeAlias = Annotated[Capability | str, open_enum_validator(Capability)]
