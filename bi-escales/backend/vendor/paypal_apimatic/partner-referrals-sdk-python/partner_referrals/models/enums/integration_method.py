from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class IntegrationMethod(str, Enum):
    """The REST-credential integration method."""

    BRAINTREE = "BRAINTREE"
    PAYPAL = "PAYPAL"
    SDK = "SDK"

    __str__ = str.__str__


IntegrationMethodOrStr: TypeAlias = Annotated[IntegrationMethod | str, open_enum_validator(IntegrationMethod)]
