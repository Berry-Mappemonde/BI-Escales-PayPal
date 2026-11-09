from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class PhoneType1(str, Enum):
    """The type of phone number provided. For example, home, work, or mobile."""

    CUSTOMER_SERVICE = "CUSTOMER_SERVICE"
    BUSINESS = "BUSINESS"

    __str__ = str.__str__


PhoneType1OrStr: TypeAlias = Annotated[PhoneType1 | str, open_enum_validator(PhoneType1)]
