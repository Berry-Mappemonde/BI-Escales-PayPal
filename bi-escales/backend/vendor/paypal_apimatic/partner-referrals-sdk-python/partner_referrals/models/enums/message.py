from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Message(str, Enum):
    REQUEST_IS_NOT_WELL_FORMED_SYNTACTICALLY_INCORRECT_OR_VIOLATES_SCHEMA = "Request is not well-formed, syntactically incorrect, or violates schema."

    __str__ = str.__str__


MessageOrStr: TypeAlias = Annotated[Message | str, open_enum_validator(Message)]
