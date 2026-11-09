from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Name6(str, Enum):
    UNPROCESSABLE_ENTITY = "UNPROCESSABLE_ENTITY"

    __str__ = str.__str__


Name6OrStr: TypeAlias = Annotated[Name6 | str, open_enum_validator(Name6)]
