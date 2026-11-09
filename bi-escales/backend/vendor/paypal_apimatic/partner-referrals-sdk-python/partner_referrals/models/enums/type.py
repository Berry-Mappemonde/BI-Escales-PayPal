from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Type(str, Enum):
    """The bank account ID type."""

    BANK_CODE = "BANK_CODE"
    BI_CODE = "BI_CODE"
    BRANCH_CODE = "BRANCH_CODE"
    ROUTING_NUMBER_1 = "ROUTING_NUMBER_1"
    ROUTING_NUMBER_2 = "ROUTING_NUMBER_2"
    ROUTING_NUMBER_3 = "ROUTING_NUMBER_3"
    SWIFT_CODE = "SWIFT_CODE"
    INTERMEDIARY_SWIFT_CODE = "INTERMEDIARY_SWIFT_CODE"
    BBAN = "BBAN"
    BBAN_ENCRYPTED = "BBAN_ENCRYPTED"
    BBAN_HMAC = "BBAN_HMAC"
    AGGREGATOR_YODLEE = "AGGREGATOR_YODLEE"

    __str__ = str.__str__


TypeOrStr: TypeAlias = Annotated[Type | str, open_enum_validator(Type)]
