from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class IntegrationType(str, Enum):
    """The type of REST-endpoint integration. To integrate with Braintree v.zero for PayPal REST endpoints, specify
    ``third_party_details``."""

    FIRST_PARTY = "FIRST_PARTY"
    THIRD_PARTY = "THIRD_PARTY"

    __str__ = str.__str__


IntegrationTypeOrStr: TypeAlias = Annotated[IntegrationType | str, open_enum_validator(IntegrationType)]
