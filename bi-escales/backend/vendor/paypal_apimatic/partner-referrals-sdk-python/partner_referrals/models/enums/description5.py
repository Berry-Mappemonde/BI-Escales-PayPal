from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Description5(str, Enum):
    YOU_DO_NOT_HAVE_PERMISSION_TO_ACCESS_OR_PERFORM_OPERATIONS_ON_THIS_RESOURCE = "You do not have permission to access or perform operations on this resource."

    __str__ = str.__str__


Description5OrStr: TypeAlias = Annotated[Description5 | str, open_enum_validator(Description5)]
