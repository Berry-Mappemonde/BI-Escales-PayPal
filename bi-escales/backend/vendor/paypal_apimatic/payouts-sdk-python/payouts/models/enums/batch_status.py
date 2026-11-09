from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class BatchStatus(str, Enum):
    """The payouts status."""

    DENIED = "DENIED"
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    CANCELED = "CANCELED"

    __str__ = str.__str__


BatchStatusOrStr: TypeAlias = Annotated[BatchStatus | str, open_enum_validator(BatchStatus)]
