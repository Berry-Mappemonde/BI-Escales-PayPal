from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Message7(str, Enum):
    AN_INTERNAL_SERVER_ERROR_OCCURRED = "An internal server error occurred."

    __str__ = str.__str__


Message7OrStr: TypeAlias = Annotated[Message7 | str, open_enum_validator(Message7)]
