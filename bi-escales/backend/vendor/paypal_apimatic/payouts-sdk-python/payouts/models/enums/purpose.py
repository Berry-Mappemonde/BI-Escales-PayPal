from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Purpose(str, Enum):
    """The purpose of the transaction."""

    AWARDS = "AWARDS"
    PRIZES = "PRIZES"
    DONATIONS = "DONATIONS"
    GOODS = "GOODS"
    SERVICES = "SERVICES"
    REBATES = "REBATES"
    CASHBACK = "CASHBACK"
    DISCOUNTS = "DISCOUNTS"
    NON_GOODS_OR_SERVICES = "NON_GOODS_OR_SERVICES"

    __str__ = str.__str__


PurposeOrStr: TypeAlias = Annotated[Purpose | str, open_enum_validator(Purpose)]
