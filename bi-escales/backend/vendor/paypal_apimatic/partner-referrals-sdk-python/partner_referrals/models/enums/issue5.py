from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Issue5(str, Enum):
    PERMISSION_DENIED = "PERMISSION_DENIED"

    __str__ = str.__str__


Issue5OrStr: TypeAlias = Annotated[Issue5 | str, open_enum_validator(Issue5)]
