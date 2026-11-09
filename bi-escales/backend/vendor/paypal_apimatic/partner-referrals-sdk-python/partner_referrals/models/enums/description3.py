from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Description3(str, Enum):
    THE_NUMBER_OF_ITEMS_IN_AN_ARRAY_PARAMETER_IS_TOO_SMALL_OR_TOO_LARGE = "the number of items in an array parameter is too small or too large"

    __str__ = str.__str__


Description3OrStr: TypeAlias = Annotated[Description3 | str, open_enum_validator(Description3)]
