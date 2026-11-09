from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Description4(str, Enum):
    THIS_API_CALL_IS_NOT_AUTHORIZED = "This API call is not authorized"

    __str__ = str.__str__


Description4OrStr: TypeAlias = Annotated[Description4 | str, open_enum_validator(Description4)]
