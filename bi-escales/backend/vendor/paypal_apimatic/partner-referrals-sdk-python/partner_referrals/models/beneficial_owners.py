from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .business_beneficial_owner import BusinessBeneficialOwner, BusinessBeneficialOwnerDict
from .individual_beneficial_owner import IndividualBeneficialOwner, IndividualBeneficialOwnerDict


class BeneficialOwners(SdkBaseModel):
    """Beneficial owners of the entity."""

    individual_beneficial_owners: Optional[list[IndividualBeneficialOwner]] = UNSET
    """Individual beneficial owners."""

    business_beneficial_owners: Optional[list[BusinessBeneficialOwner]] = UNSET
    """Business beneficial owners."""


class BeneficialOwnersDict(TypedDict):
    individual_beneficial_owners: NotRequired[list[IndividualBeneficialOwnerDict]]
    business_beneficial_owners: NotRequired[list[BusinessBeneficialOwnerDict]]
