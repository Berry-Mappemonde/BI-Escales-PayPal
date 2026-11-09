from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Message2(str, Enum):
    AUTHORIZATION_FAILED_DUE_TO_INSUFFICIENT_PERMISSIONS = "Authorization failed due to insufficient permissions."

    __str__ = str.__str__


Message2OrStr: TypeAlias = Annotated[Message2 | str, open_enum_validator(Message2)]
