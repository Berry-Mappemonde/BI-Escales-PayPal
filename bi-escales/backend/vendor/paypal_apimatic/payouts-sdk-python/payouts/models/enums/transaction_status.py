from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class TransactionStatus(str, Enum):
    """The item transaction status.<blockquote><strong>Note:</strong> For
    <code>POST/v1/payments/payouts-item/{payout_item_id}/cancel</code>, the only possible
    <code>transaction_status</code> value is <code>RETURNED</code>.</blockquote>"""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PENDING = "PENDING"
    UNCLAIMED = "UNCLAIMED"
    RETURNED = "RETURNED"
    ONHOLD = "ONHOLD"
    BLOCKED = "BLOCKED"
    REFUNDED = "REFUNDED"
    REVERSED = "REVERSED"

    __str__ = str.__str__


TransactionStatusOrStr: TypeAlias = Annotated[TransactionStatus | str, open_enum_validator(TransactionStatus)]
