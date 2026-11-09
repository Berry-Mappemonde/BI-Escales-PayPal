from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class Description7(str, Enum):
    ACCOUNT_HAS_NOT_BEEN_CONFIGURED_TO_USE_PAY_PAL_COMPLETE_PAYMENTS = "Account has not been configured to use PayPal Complete Payments"

    __str__ = str.__str__


Description7OrStr: TypeAlias = Annotated[Description7 | str, open_enum_validator(Description7)]
