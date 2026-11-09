from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class RecipientWallet(str, Enum):
    """The wallet where the recipient receives the payout. Payouts to Venmo recipients require a 'note' string and a US
    mobile phone number."""

    PAYPAL = "PAYPAL"
    VENMO = "VENMO"

    __str__ = str.__str__


RecipientWalletOrStr: TypeAlias = Annotated[RecipientWallet | str, open_enum_validator(RecipientWallet)]
