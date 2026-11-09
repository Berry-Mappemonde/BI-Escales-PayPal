from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Issue3(str, Enum):
    INVALID_ARRAY_LENGTH = "INVALID_ARRAY_LENGTH"

    __str__ = str.__str__


Issue3OrStr: TypeAlias = Annotated[Issue3 | str, open_enum_validator(Issue3)]
