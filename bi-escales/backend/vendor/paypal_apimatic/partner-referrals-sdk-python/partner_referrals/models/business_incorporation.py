from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel


class BusinessIncorporation(SdkBaseModel):
    """Business incorporation information."""

    incorporation_country_code: Optional[str] = UNSET
    """The `two-character ISO 3166-1 code </docs/api/reference/country-codes/>`__ that identifies the country or
    region.<blockquote><strong>Note:</strong> The country code for Great Britain is <code>GB</code> and not
    <code>UK</code> as used in the top-level domain names for that country. Use the ``C2`` country code for China
    worldwide for comparable uncontrolled price (CUP) method, bank card, and cross-border transactions.</blockquote>"""

    incorporation_date: Optional[str] = UNSET
    """The stand-alone date, in `Internet date and time format <https://tools.ietf.org/html/rfc3339#section-5.6>`__. To
    represent special legal values, such as a date of birth, you should use dates with no associated time or time-zone
    data. Whenever possible, use the standard ``date_time`` type. This regular expression does not validate all dates.
    For example, February 31 is valid and nothing is known about leap years."""


class BusinessIncorporationDict(TypedDict):
    incorporation_country_code: NotRequired[str]
    incorporation_date: NotRequired[str]
