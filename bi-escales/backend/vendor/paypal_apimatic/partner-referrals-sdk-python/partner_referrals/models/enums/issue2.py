from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Issue2(str, Enum):
    INVALID_PARAMETER_VALUE = "INVALID_PARAMETER_VALUE"

    __str__ = str.__str__


Issue2OrStr: TypeAlias = Annotated[Issue2 | str, open_enum_validator(Issue2)]
