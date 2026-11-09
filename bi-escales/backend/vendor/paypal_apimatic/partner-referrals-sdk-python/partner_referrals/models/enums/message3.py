from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Message3(str, Enum):
    THE_SPECIFIED_RESOURCE_DOES_NOT_EXIST = "The specified resource does not exist."

    __str__ = str.__str__


Message3OrStr: TypeAlias = Annotated[Message3 | str, open_enum_validator(Message3)]
