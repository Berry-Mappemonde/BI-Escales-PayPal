from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .currency import Currency, CurrencyDict
from .enums.purpose import PurposeOrStr
from .enums.recipient_type import RecipientTypeOrStr
from .enums.recipient_wallet import RecipientWallet, RecipientWalletOrStr
from .name import Name, NameDict


class PayoutItemDetail(SdkBaseModel):
    """The details for a sender-created payout to a single recipient."""

    recipient_type: Optional[RecipientTypeOrStr] = UNSET
    """The ID type that identifies the payment receiver."""

    amount: Currency
    """The currency and amount for a financial transaction, such as a balance or payment due."""

    note: Optional[str] = UNSET
    """The sender-specified note for notifications. Supports up to 4000 ASCII characters and 1000 non-ASCII
    characters."""

    receiver: str
    """The receiver of the payment. Corresponds to the ``recipient_type`` value in the request."""

    sender_item_id: Optional[str] = UNSET
    """A sender-specified ID number. Tracks the payout in an accounting system."""

    recipient_name: Optional[Name] = UNSET
    """The name of the party."""

    recipient_wallet: RecipientWalletOrStr = RecipientWallet.PAYPAL
    """The wallet where the recipient receives the payout. Payouts to Venmo recipients require a 'note' string and a US
    mobile phone number."""

    purpose: Optional[PurposeOrStr] = UNSET
    """The purpose of the transaction."""


class PayoutItemDetailDict(TypedDict):
    recipient_type: NotRequired[RecipientTypeOrStr]
    amount: CurrencyDict
    note: NotRequired[str]
    receiver: str
    sender_item_id: NotRequired[str]
    recipient_name: NotRequired[NameDict]
    recipient_wallet: NotRequired[RecipientWalletOrStr]
    purpose: NotRequired[PurposeOrStr]
