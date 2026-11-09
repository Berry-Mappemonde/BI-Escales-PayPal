from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class PersonAddressType(str, Enum):
    """The address type under which the provided address is tagged."""

    HOME = "HOME"

    __str__ = str.__str__


PersonAddressTypeOrStr: TypeAlias = Annotated[PersonAddressType | str, open_enum_validator(PersonAddressType)]
