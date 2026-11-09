from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .alternate_notification_method import AlternateNotificationMethod, AlternateNotificationMethodDict
from .application_context import ApplicationContext, ApplicationContextDict
from .currency import Currency, CurrencyDict
from .enums.purpose import PurposeOrStr


class PayoutItem(SdkBaseModel):
    """The sender-created payout to a recipient."""

    recipient_type: Optional[str] = UNSET
    """The recipient type. Value is:<ul><li><p><code>EMAIL</code>. The unencrypted email. Value is a string of up to 127
    single-byte characters.</p></li><li><p><code>PHONE</code>. The unencrypted phone
    number.</p><blockquote><strong>Note:</strong> The PayPal sandbox does not support the <code>PHONE</code> recipient
    type.</blockquote></li><li><p><code>PAYPAL_ID</code>. The encrypted PayPal account
    number.</p></li><li><p><code>USER_HANDLE</code>. User handle (or) Username associated with Venmo
    account.</p></li></ul><br/>If the <code>sender_batch_header</code> includes the <code>recipient_type</code>
    attribute, payout items use the <code>recipient_type</code> of the <code>sender_batch_header</code>, unless a payout
    item has its own <code>recipient_type</code> attribute. If the <code>sender_batch_header</code> omits the
    <code>recipient_type</code> attribute, each payout item must include its own <code>recipient_type</code> value."""

    amount: Currency
    """The currency and amount for a financial transaction, such as a balance or payment due."""

    note: Optional[str] = UNSET
    """The sender-specified note for notifications. Supports up to 4000 ASCII characters and 1000 non-ASCII
    characters."""

    receiver: str
    """The receiver of the payment. Corresponds to the ``recipient_type`` value in the request. Max value of up to 127
    single-byte characters."""

    sender_item_id: Optional[str] = UNSET
    """The sender-specified ID number. Tracks the payout in an accounting system."""

    recipient_wallet: str = "PAYPAL"
    """The recipient wallet."""

    alternate_notification_method: Optional[AlternateNotificationMethod] = UNSET
    """Captures additional notification modes to reach out to the receiver regarding this payment."""

    notification_language: Optional[str] = UNSET
    """The `language tag <https://tools.ietf.org/html/bcp47#section-2>`__ for the language in which to localize the
    error-related strings, such as messages, issues, and suggested actions. The tag is made up of the `ISO 639-2
    language code <https://www.loc.gov/standards/iso639-2/php/code_list.php>`__, the optional `ISO-15924 script tag
    <https://www.unicode.org/iso15924/codelists.html>`__, and the `ISO-3166 alpha-2 country code
    </docs/integration/direct/rest/country-codes/>`__."""

    application_context: Optional[ApplicationContext] = UNSET
    """Metadata for Venmo transactions."""

    purpose: Optional[PurposeOrStr] = UNSET
    """The purpose of the transaction."""


class PayoutItemDict(TypedDict):
    recipient_type: NotRequired[str]
    amount: CurrencyDict
    note: NotRequired[str]
    receiver: str
    sender_item_id: NotRequired[str]
    recipient_wallet: NotRequired[str]
    alternate_notification_method: NotRequired[AlternateNotificationMethodDict]
    notification_language: NotRequired[str]
    application_context: NotRequired[ApplicationContextDict]
    purpose: NotRequired[PurposeOrStr]
