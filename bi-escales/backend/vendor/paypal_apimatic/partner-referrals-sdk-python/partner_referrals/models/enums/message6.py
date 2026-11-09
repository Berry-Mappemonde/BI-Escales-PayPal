from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Message6(str, Enum):
    THE_REQUESTED_ACTION_FAILED_BUSINESS_VALIDATION = "The requested action failed business validation."

    __str__ = str.__str__


Message6OrStr: TypeAlias = Annotated[Message6 | str, open_enum_validator(Message6)]
