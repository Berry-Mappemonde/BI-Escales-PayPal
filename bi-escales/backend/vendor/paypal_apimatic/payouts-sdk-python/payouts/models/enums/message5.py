from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Message5(str, Enum):
    THE_SERVER_DOES_NOT_SUPPORT_THE_REQUEST_PAYLOAD_S_MEDIA_TYPE = "The server does not support the request payload's media type."

    __str__ = str.__str__


Message5OrStr: TypeAlias = Annotated[Message5 | str, open_enum_validator(Message5)]
