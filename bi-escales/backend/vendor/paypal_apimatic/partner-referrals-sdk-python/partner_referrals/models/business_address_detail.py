from __future__ import annotations

from typing import Literal

from pydantic import Field
from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .address_details import AddressDetails, AddressDetailsDict


class BusinessAddressDetail(SdkBaseModel):
    address_line_1: Optional[str] = UNSET
    """The first line of the address. For example, number or street. For example, ``173 Drury Lane``. Required for data
    entry and compliance and risk checks. Must contain the full address."""

    address_line_2: Optional[str] = UNSET
    """The second line of the address. For example, suite or apartment number."""

    address_line_3: Optional[str] = UNSET
    """The third line of the address, if needed. For example, a street complement for Brazil, direction text, such as
    ``next to Walmart``, or a landmark in an Indian address."""

    admin_area_4: Optional[str] = UNSET
    """The neighborhood, ward, or district. Smaller than ``admin_area_level_3`` or ``sub_locality``. Value
    is:<ul><li>The postal sorting code for Guernsey and many French territories, such as French Guiana.</li><li>The
    fine-grained administrative levels in China.</li></ul>"""

    admin_area_3: Optional[str] = UNSET
    """A sub-locality, suburb, neighborhood, or district. Smaller than ``admin_area_level_2``. Value is:<ul><li>Brazil.
    Suburb, bairro, or neighborhood.</li><li>India. Sub-locality or district. Street name information is not always
    available but a sub-locality or district can be a very small area.</li></ul>"""

    admin_area_2: Optional[str] = UNSET
    """A city, town, or village. Smaller than ``admin_area_level_1``."""

    admin_area_1: Optional[str] = UNSET
    """The highest level sub-division in a country, which is usually a province, state, or ISO-3166-2 subdivision.
    Format for postal delivery. For example, ``CA`` and not ``California``. Value, by country, is:<ul><li>UK. A
    county.</li><li>US. A state.</li><li>Canada. A province.</li><li>Japan. A prefecture.</li><li>Switzerland. A
    kanton.</li></ul>"""

    postal_code: Optional[str] = UNSET
    """The postal code, which is the zip code or equivalent. Typically required for countries with a postal code or an
    equivalent. See `postal code <https://en.wikipedia.org/wiki/Postal_code>`__."""

    country_code: str
    """The `two-character ISO 3166-1 code </docs/api/reference/country-codes/>`__ that identifies the country or
    region.<blockquote><strong>Note:</strong> The country code for Great Britain is <code>GB</code> and not
    <code>UK</code> as used in the top-level domain names for that country. Use the ``C2`` country code for China
    worldwide for comparable uncontrolled price (CUP) method, bank card, and cross-border transactions.</blockquote>"""

    address_details: Optional[AddressDetails] = UNSET
    """The non-portable additional address details that are sometimes needed for compliance, risk, or other scenarios
    where fine-grain address information might be needed. Not portable with common third party and open source.
    Redundant with core fields.<br/>For example, ``address_portable.address_line_1`` is usually a combination of
    ``address_details.street_number``, ``street_name``, and ``street_type``."""

    type_: Literal["WORK"] = Field(default="WORK", alias="type")
    """Address type under which the provided address is tagged"""


class BusinessAddressDetailDict(TypedDict):
    address_line_1: NotRequired[str]
    address_line_2: NotRequired[str]
    address_line_3: NotRequired[str]
    admin_area_4: NotRequired[str]
    admin_area_3: NotRequired[str]
    admin_area_2: NotRequired[str]
    admin_area_1: NotRequired[str]
    postal_code: NotRequired[str]
    country_code: str
    address_details: NotRequired[AddressDetailsDict]
    type_: Literal["WORK"]
