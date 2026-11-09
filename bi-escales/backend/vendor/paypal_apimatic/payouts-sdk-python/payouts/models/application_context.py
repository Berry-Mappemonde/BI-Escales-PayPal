from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel


class ApplicationContext(SdkBaseModel):
    """Metadata for Venmo transactions."""

    social_feed_privacy: str = "PRIVATE"
    """This attribute controls the privacy of a payout transaction in recipient’s feed. PUBLIC, FRIENDS_ONLY & PRIVATE
    are the values that can be used. PUBLIC - The payment displays on the recipient's public Venmo feed. FRIENDS_ONLY -
    The payment displays only to the recipient's Venmo friends. PRIVATE - The payment displays only on the recipient's
    personal feed. Defaults to ``PRIVATE`` if left blank."""

    holler_url: Optional[str] = UNSET
    """Link to a Holler sticker. For Venmo recipients, the sticker displays with the payout message. The maximum URL
    length is 151."""

    logo_url: Optional[str] = UNSET
    """Link to a logo that displays as the sender's profile image in the recipient's Venmo feed. Used to add or update
    the business profile image. Max image size: 1024 x 1024 pixels. The image should be square and maximum URL length is
    2000."""


class ApplicationContextDict(TypedDict):
    social_feed_privacy: NotRequired[str]
    holler_url: NotRequired[str]
    logo_url: NotRequired[str]
