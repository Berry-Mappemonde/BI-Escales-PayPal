from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class SignupMode(str, Enum):
    """Signup Mode to be used for sellers for third party integration."""

    VERIFY_WITH_PAYPAL = "VERIFY_WITH_PAYPAL"

    __str__ = str.__str__


SignupModeOrStr: TypeAlias = Annotated[SignupMode | str, open_enum_validator(SignupMode)]
