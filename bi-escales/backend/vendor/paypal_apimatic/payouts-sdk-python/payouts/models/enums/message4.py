from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Message4(str, Enum):
    THE_SERVER_HAS_DETECTED_A_CONFLICT_WHILE_PROCESSING_THIS_REQUEST = "The server has detected a conflict while processing this request."

    __str__ = str.__str__


Message4OrStr: TypeAlias = Annotated[Message4 | str, open_enum_validator(Message4)]
