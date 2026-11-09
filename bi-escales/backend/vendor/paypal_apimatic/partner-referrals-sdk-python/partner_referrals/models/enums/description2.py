from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Description2(str, Enum):
    THE_VALUE_OF_A_FIELD_IS_INVALID = "the value of a field is invalid"

    __str__ = str.__str__


Description2OrStr: TypeAlias = Annotated[Description2 | str, open_enum_validator(Description2)]
