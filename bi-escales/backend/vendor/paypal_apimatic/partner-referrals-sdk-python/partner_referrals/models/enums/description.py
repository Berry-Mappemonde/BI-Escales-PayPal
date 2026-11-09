from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Description(str, Enum):
    THE_VALUE_OF_A_FIELD_IS_EITHER_TOO_SHORT_OR_TOO_LONG = "the value of a field is either too short or too long"

    __str__ = str.__str__


DescriptionOrStr: TypeAlias = Annotated[Description | str, open_enum_validator(Description)]
