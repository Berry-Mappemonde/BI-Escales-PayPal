from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Message8(str, Enum):
    SERVICE_UNAVAILABLE = "Service Unavailable."

    __str__ = str.__str__


Message8OrStr: TypeAlias = Annotated[Message8 | str, open_enum_validator(Message8)]
