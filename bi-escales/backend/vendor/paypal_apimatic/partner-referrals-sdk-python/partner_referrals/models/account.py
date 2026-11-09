from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .business_entity import BusinessEntity, BusinessEntityDict
from .individual_owner import IndividualOwner, IndividualOwnerDict


class Account(SdkBaseModel):
    """Common account object to hold the account related details of the customer."""

    individual_owners: Optional[list[IndividualOwner]] = UNSET
    """List of owners in the account. There should be only one primary account owner which is mentioned in their
    role_type."""

    business_entity: Optional[BusinessEntity] = UNSET


class AccountDict(TypedDict):
    individual_owners: NotRequired[list[IndividualOwnerDict]]
    business_entity: NotRequired[BusinessEntityDict]
