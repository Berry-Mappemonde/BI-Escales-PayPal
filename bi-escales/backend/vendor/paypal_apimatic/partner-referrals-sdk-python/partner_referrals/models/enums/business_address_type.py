from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class BusinessAddressType(str, Enum):
    """Address type under which the provided address is tagged"""

    WORK = "WORK"

    __str__ = str.__str__


BusinessAddressTypeOrStr: TypeAlias = Annotated[BusinessAddressType | str, open_enum_validator(BusinessAddressType)]
