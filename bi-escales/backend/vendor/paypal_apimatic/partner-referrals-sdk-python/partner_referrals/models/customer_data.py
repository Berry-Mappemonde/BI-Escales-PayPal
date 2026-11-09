from __future__ import annotations

from typing import Any

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .business_entity import BusinessEntity, BusinessEntityDict
from .enums.capability import CapabilityOrStr
from .enums.product_name import ProductNameOrStr
from .financial_instrument import FinancialInstrument, FinancialInstrumentDict
from .individual_owner import IndividualOwner, IndividualOwnerDict
from .legal_consent import LegalConsent, LegalConsentDict
from .operation import Operation, OperationDict
from .partner_configuration_override import PartnerConfigurationOverride, PartnerConfigurationOverrideDict
from .payout_attributes import PayoutAttributes, PayoutAttributesDict


class CustomerData(SdkBaseModel):
    """The customer's referral data that partners share with PayPal."""

    individual_owners: Optional[list[IndividualOwner]] = UNSET
    """List of owners in the account. There should be only one primary account owner which is mentioned in their
    role_type."""

    business_entity: Optional[BusinessEntity] = UNSET
    email: Optional[str] = UNSET
    """The internationalized email address.<blockquote><strong>Note:</strong> Up to 64 characters are allowed before and
    255 characters are allowed after the <code>@</code> sign. However, the generally accepted maximum length for an
    email address is 254 characters. The pattern verifies that an unquoted <code>@</code> sign exists.</blockquote>"""

    preferred_language_code: Optional[str] = UNSET
    """The `language tag <https://tools.ietf.org/html/bcp47#section-2>`__ for the language in which to localize the
    error-related strings, such as messages, issues, and suggested actions. The tag is made up of the `ISO 639-2
    language code <https://www.loc.gov/standards/iso639-2/php/code_list.php>`__, the optional `ISO-15924 script tag
    <https://www.unicode.org/iso15924/codelists.html>`__, and the `ISO-3166 alpha-2 country code
    </docs/integration/direct/rest/country-codes/>`__."""

    tracking_id: Optional[str] = UNSET
    """The partner's unique identifier for this customer in their system which can be used to track user in PayPal."""

    partner_config_override: Optional[PartnerConfigurationOverride] = UNSET
    """The preference to customize the web experience of the customer by overriding that is set at the Partner's
    Account."""

    financial_instruments: Optional[FinancialInstrument] = UNSET
    """Financial instruments attached to this account."""

    operations: list[Operation]
    """An array of operations to perform for the customer while they share their data."""

    products: Optional[list[ProductNameOrStr]] = UNSET
    """An array of PayPal products to which the partner wants to onboard the customer."""

    capabilities: Optional[list[CapabilityOrStr]] = UNSET
    """An array of capabilities which the partner wants to enable for the selected products. Supported only when
    products are specified."""

    outside_process_dependencies: Optional[list[Any]] = UNSET
    """An array of dependent processes."""

    legal_consents: list[LegalConsent]
    """An array of all consents that the partner has received from this seller. If ``SHARE_DATA_CONSENT`` is not
    granted, PayPal does not store customer data."""

    payout_attributes: Optional[PayoutAttributes] = UNSET
    """Payout specific attributes."""

    legal_country_code: Optional[str] = UNSET
    """The `two-character ISO 3166-1 code </docs/api/reference/country-codes/>`__ that identifies the country or
    region.<blockquote><strong>Note:</strong> The country code for Great Britain is <code>GB</code> and not
    <code>UK</code> as used in the top-level domain names for that country. Use the ``C2`` country code for China
    worldwide for comparable uncontrolled price (CUP) method, bank card, and cross-border transactions.</blockquote>"""


class CustomerDataDict(TypedDict):
    individual_owners: NotRequired[list[IndividualOwnerDict]]
    business_entity: NotRequired[BusinessEntityDict]
    email: NotRequired[str]
    preferred_language_code: NotRequired[str]
    tracking_id: NotRequired[str]
    partner_config_override: NotRequired[PartnerConfigurationOverrideDict]
    financial_instruments: NotRequired[FinancialInstrumentDict]
    operations: list[OperationDict]
    products: NotRequired[list[ProductNameOrStr]]
    capabilities: NotRequired[list[CapabilityOrStr]]
    outside_process_dependencies: NotRequired[list[Any]]
    legal_consents: list[LegalConsentDict]
    payout_attributes: NotRequired[PayoutAttributesDict]
    legal_country_code: NotRequired[str]
