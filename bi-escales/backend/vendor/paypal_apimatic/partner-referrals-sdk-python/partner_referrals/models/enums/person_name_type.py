from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class PersonNameType(str, Enum):
    """The person's name type."""

    LEGAL = "LEGAL"

    __str__ = str.__str__


PersonNameTypeOrStr: TypeAlias = Annotated[PersonNameType | str, open_enum_validator(PersonNameType)]
