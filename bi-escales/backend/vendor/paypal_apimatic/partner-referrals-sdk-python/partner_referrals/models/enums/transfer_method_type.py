from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class TransferMethodType(str, Enum):
    """Transfer Method type."""

    BANK_ACCOUNT = "BANK_ACCOUNT"
    PAYPAL = "PAYPAL"
    VENMO = "VENMO"
    WIRE_ACCOUNT = "WIRE_ACCOUNT"

    __str__ = str.__str__


TransferMethodTypeOrStr: TypeAlias = Annotated[TransferMethodType | str, open_enum_validator(TransferMethodType)]
