from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Issue1(str, Enum):
    INVALID_PARAMETER_SYNTAX = "INVALID_PARAMETER_SYNTAX"

    __str__ = str.__str__


Issue1OrStr: TypeAlias = Annotated[Issue1 | str, open_enum_validator(Issue1)]
