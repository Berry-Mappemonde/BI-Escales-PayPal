from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .file_reference import FileReference, FileReferenceDict
from .link_description import LinkDescription, LinkDescriptionDict


class Document(SdkBaseModel):
    """The document object."""

    id: Optional[str] = UNSET
    """The encrypted identifier for the document."""

    labels: Optional[list[str]] = UNSET
    """The document labels. A document could be classfied to multiple categories. For example, a bill document can be
    classfified as ``BILL DOCUMENT`` and ``UTILITY DOCUMENT``."""

    name: Optional[str] = UNSET
    """The file name."""

    identification_number: Optional[str] = UNSET
    """The number for the document. It is the ID number if the document is ``ID CARD``, the passport number if the
    document is ``PASSPORT``, etc."""

    issue_date: Optional[str] = UNSET
    """The stand-alone date, in `Internet date and time format <https://tools.ietf.org/html/rfc3339#section-5.6>`__. To
    represent special legal values, such as a date of birth, you should use dates with no associated time or time-zone
    data. Whenever possible, use the standard ``date_time`` type. This regular expression does not validate all dates.
    For example, February 31 is valid and nothing is known about leap years."""

    expiry_date: Optional[str] = UNSET
    """The stand-alone date, in `Internet date and time format <https://tools.ietf.org/html/rfc3339#section-5.6>`__. To
    represent special legal values, such as a date of birth, you should use dates with no associated time or time-zone
    data. Whenever possible, use the standard ``date_time`` type. This regular expression does not validate all dates.
    For example, February 31 is valid and nothing is known about leap years."""

    issuing_country_code: Optional[str] = UNSET
    """The `two-character ISO 3166-1 code </docs/api/reference/country-codes/>`__ that identifies the country or
    region.<blockquote><strong>Note:</strong> The country code for Great Britain is <code>GB</code> and not
    <code>UK</code> as used in the top-level domain names for that country. Use the ``C2`` country code for China
    worldwide for comparable uncontrolled price (CUP) method, bank card, and cross-border transactions.</blockquote>"""

    files: Optional[list[FileReference]] = UNSET
    """The files contained in the document. For example, a document could be represented by a front page file and a back
    page file, etc."""

    links: Optional[list[LinkDescription]] = UNSET
    """The HATEOAS links."""


class DocumentDict(TypedDict):
    id: NotRequired[str]
    labels: NotRequired[list[str]]
    name: NotRequired[str]
    identification_number: NotRequired[str]
    issue_date: NotRequired[str]
    expiry_date: NotRequired[str]
    issuing_country_code: NotRequired[str]
    files: NotRequired[list[FileReferenceDict]]
    links: NotRequired[list[LinkDescriptionDict]]
