from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Description1(str, Enum):
    THE_VALUE_OF_A_FIELD_DOES_NOT_CONFORM_TO_THE_EXPECTED_FORMAT = "the value of a field does not conform to the expected format"

    __str__ = str.__str__


Description1OrStr: TypeAlias = Annotated[Description1 | str, open_enum_validator(Description1)]
