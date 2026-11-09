from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel


class SenderBatchHeader(SdkBaseModel):
    """The sender-provided payout header for a payout request."""

    sender_batch_id: Optional[str] = UNSET
    """A sender-specified ID number. Tracks the payout in an accounting system.<blockquote><strong>Note:</strong>
    <p>PayPal does not process duplicate payouts. If you specify a <code>sender_batch_id</code> that was used in the
    last 30 days, the API rejects the request with an error message that shows the duplicate
    <code>sender_batch_id</code> and includes a HATEOAS link to the original payout with the same
    <code>sender_batch_id</code>.</p><p>If you receive an HTTP <code>5<i>nn</i></code> status code, you can safely retry
    the request with the same <code>sender_batch_id</code>. The API completes a payment only once for a
    <code>sender_batch_id</code> that is used within 30 days.</p></blockquote>"""

    recipient_type: Optional[str] = UNSET
    """The ID type that identifies the recipient of the payment. For example, <code>EMAIL</code>."""

    email_subject: Optional[str] = UNSET
    """The subject line for the email that PayPal sends when payment for a payout item completes. The subject line is
    the same for all recipients. Value is an alphanumeric string of up to 255 single-byte characters."""

    email_message: Optional[str] = UNSET
    """The email message that PayPal sends when the payout item completes. The message is the same for all
    recipients."""

    note: Optional[str] = UNSET
    """The payouts and item-level notes are concatenated in the email. The maximum combined length of the notes is 1000
    characters."""


class SenderBatchHeaderDict(TypedDict):
    sender_batch_id: NotRequired[str]
    recipient_type: NotRequired[str]
    email_subject: NotRequired[str]
    email_message: NotRequired[str]
    note: NotRequired[str]
