from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Description10(str, Enum):
    """The human-readable description for an issue. The description can change over the lifetime of an API, so clients
    must not depend on this value."""

    YOU_DO_NOT_HAVE_PERMISSION_TO_ACCESS_OR_PERFORM_OPERATIONS_ON_THIS_RESOURCE = "You do not have permission to access or perform operations on this resource."

    __str__ = str.__str__


Description10OrStr: TypeAlias = Annotated[Description10 | str, open_enum_validator(Description10)]
