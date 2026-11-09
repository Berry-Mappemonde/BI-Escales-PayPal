from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Message1(str, Enum):
    AUTHENTICATION_FAILED_DUE_TO_MISSING_AUTHORIZATION_HEADER_OR_INVALID_AUTHENTICATION_CREDENTIALS = "Authentication failed due to missing authorization header, or invalid authentication credentials."

    __str__ = str.__str__


Message1OrStr: TypeAlias = Annotated[Message1 | str, open_enum_validator(Message1)]
