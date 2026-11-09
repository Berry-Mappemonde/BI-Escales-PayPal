from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel


class PortablePostalAddressMediumGrained1(SdkBaseModel):
    """The portable international postal address. Maps to `AddressValidationMetadata
    <https://github.com/googlei18n/libaddressinput/wiki/AddressValidationMetadata>`__ and HTML 5.1 `Autofilling form
    controls: the autocomplete attribute
    <https://www.w3.org/TR/html51/sec-forms.html#autofilling-form-controls-the-autocomplete-attribute>`__."""

    address_line_1: Optional[str] = UNSET
    """The first line of the address. For example, number or street. For example, ``173 Drury Lane``. Required for data
    entry and compliance and risk checks. Must contain the full address."""

    address_line_2: Optional[str] = UNSET
    """The second line of the address. For example, suite or apartment number."""

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
    """The `two-character ISO 3166-1 code </docs/integration/direct/rest/country-codes/>`__ that identifies the country
    or region.<blockquote><strong>Note:</strong> The country code for Great Britain is <code>GB</code> and not
    <code>UK</code> as used in the top-level domain names for that country. Use the ``C2`` country code for China
    worldwide for comparable uncontrolled price (CUP) method, bank card, and cross-border transactions.</blockquote>"""


class PortablePostalAddressMediumGrained1Dict(TypedDict):
    address_line_1: NotRequired[str]
    address_line_2: NotRequired[str]
    admin_area_2: NotRequired[str]
    admin_area_1: NotRequired[str]
    postal_code: NotRequired[str]
    country_code: str
