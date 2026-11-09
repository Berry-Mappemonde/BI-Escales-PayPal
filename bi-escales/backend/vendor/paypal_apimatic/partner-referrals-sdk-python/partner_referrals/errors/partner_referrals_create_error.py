from __future__ import annotations

from dataclasses import dataclass
from typing import Final, TypeAlias

from ..core import ErrorMapper, RawError, decode_json
from ..models.internal_server_error import InternalServerError
from ..models.v2_customer_partner_referrals400_error1 import V2CustomerPartnerReferrals400Error1
from ..models.v2_customer_partner_referrals401_error1 import V2CustomerPartnerReferrals401Error1
from ..models.v2_customer_partner_referrals403_error1 import V2CustomerPartnerReferrals403Error1
from ..models.v2_customer_partner_referrals422_error1 import V2CustomerPartnerReferrals422Error1

PartnerReferralsCreateErrorBody: TypeAlias = (
    V2CustomerPartnerReferrals400Error1
    | V2CustomerPartnerReferrals401Error1
    | V2CustomerPartnerReferrals403Error1
    | V2CustomerPartnerReferrals422Error1
    | InternalServerError
    | RawError
)


@dataclass(frozen=True, slots=True)
class _PartnerReferralsCreateError:
    def map(self, status_code: int, content: bytes) -> PartnerReferralsCreateErrorBody:
        match status_code:
            case 400:
                return decode_json[V2CustomerPartnerReferrals400Error1](content)
            case 401:
                return decode_json[V2CustomerPartnerReferrals401Error1](content)
            case 403:
                return decode_json[V2CustomerPartnerReferrals403Error1](content)
            case 422:
                return decode_json[V2CustomerPartnerReferrals422Error1](content)
            case 500:
                return decode_json[InternalServerError](content)
            case _:
                return RawError(status_code, content)


partner_referrals_create_error_mapper: Final[
    ErrorMapper[PartnerReferralsCreateErrorBody]
] = _PartnerReferralsCreateError()
