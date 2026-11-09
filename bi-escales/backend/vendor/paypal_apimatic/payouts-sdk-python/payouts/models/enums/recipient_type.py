from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class RecipientType(str, Enum):
    """The ID type that identifies the payment receiver."""

    EMAIL = "EMAIL"
    PHONE = "PHONE"
    PAYPAL_ID = "PAYPAL_ID"

    __str__ = str.__str__


RecipientTypeOrStr: TypeAlias = Annotated[RecipientType | str, open_enum_validator(RecipientType)]
