from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel


class FileReference(SdkBaseModel):
    """The file reference. Can be a file in PayPal MediaServ, PayPal DMS, or another custom store."""

    id: Optional[str] = UNSET
    """The ID of the referenced file."""

    reference_url: Optional[str] = UNSET
    """The reference URL for the file."""

    content_type: Optional[str] = UNSET
    """The `Internet Assigned Numbers Authority (IANA) media type of the file
    <https://www.iana.org/assignments/media-types/media-types.xhtml>`__."""

    create_time: Optional[str] = UNSET
    """The date and time, in `Internet date and time format <https://tools.ietf.org/html/rfc3339#section-5.6>`__.
    Seconds are required while fractional seconds are optional.<blockquote><strong>Note:</strong> The regular expression
    provides guidance but does not reject all invalid dates.</blockquote>"""

    size: Optional[str] = UNSET
    """The size of the file, in bytes."""


class FileReferenceDict(TypedDict):
    id: NotRequired[str]
    reference_url: NotRequired[str]
    content_type: NotRequired[str]
    create_time: NotRequired[str]
    size: NotRequired[str]
