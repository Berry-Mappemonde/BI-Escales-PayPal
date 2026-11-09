from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .bank_account_identifier import BankAccountIdentifier, BankAccountIdentifierDict
from .enums.account_type import AccountTypeOrStr
from .mandate import Mandate, MandateDict
from .portable_postal_address_medium_grained1 import (
    PortablePostalAddressMediumGrained1,
    PortablePostalAddressMediumGrained1Dict,
)


class BankAccount(SdkBaseModel):
    """The bank account information."""

    nick_name: Optional[str] = UNSET
    """The user-provided short name for the user's bank account."""

    account_number: str
    """The bank account number."""

    account_type: AccountTypeOrStr
    """The type of bank account."""

    currency_code: Optional[str] = UNSET
    """The `three-character ISO-4217 currency code </docs/integration/direct/rest/currency-codes/>`__ that identifies
    the currency."""

    identifiers: Optional[list[BankAccountIdentifier]] = UNSET
    """An array of instrument institute attributes. Used with the account number to uniquely identify the instrument.
    Value is:<ul><li>For banks with IBAN information, the IBAN number.</li><li>For banks with BBAN information, the BBAN
    number.</li><li>For banks with both IBAN and BBAN information, the IBAN number.</li></ul>"""

    branch_location: Optional[PortablePostalAddressMediumGrained1] = UNSET
    """The portable international postal address. Maps to `AddressValidationMetadata
    <https://github.com/googlei18n/libaddressinput/wiki/AddressValidationMetadata>`__ and HTML 5.1 `Autofilling form
    controls: the autocomplete attribute
    <https://www.w3.org/TR/html51/sec-forms.html#autofilling-form-controls-the-autocomplete-attribute>`__."""

    mandate: Optional[Mandate] = UNSET
    """Seller’s consent to operate on this financial instrument."""


class BankAccountDict(TypedDict):
    nick_name: NotRequired[str]
    account_number: str
    account_type: AccountTypeOrStr
    currency_code: NotRequired[str]
    identifiers: NotRequired[list[BankAccountIdentifierDict]]
    branch_location: NotRequired[PortablePostalAddressMediumGrained1Dict]
    mandate: NotRequired[MandateDict]
