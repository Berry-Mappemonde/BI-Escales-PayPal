from __future__ import annotations

from dataclasses import dataclass
from typing import Final, TypeAlias

from ..core import ErrorMapper, RawError, decode_json
from ..models.internal_server_error import InternalServerError
from ..models.v2_customer_partner_referrals401_error1 import V2CustomerPartnerReferrals401Error1
from ..models.v2_customer_partner_referrals403_error1 import V2CustomerPartnerReferrals403Error1

PartnerReferralsReadErrorBody: TypeAlias = (
    V2CustomerPartnerReferrals401Error1 | V2CustomerPartnerReferrals403Error1 | InternalServerError | RawError
)


@dataclass(frozen=True, slots=True)
class _PartnerReferralsReadError:
    def map(self, status_code: int, content: bytes) -> PartnerReferralsReadErrorBody:
        match status_code:
            case 401:
                return decode_json[V2CustomerPartnerReferrals401Error1](content)
            case 403:
                return decode_json[V2CustomerPartnerReferrals403Error1](content)
            case 500:
                return decode_json[InternalServerError](content)
            case _:
                return RawError(status_code, content)


partner_referrals_read_error_mapper: Final[ErrorMapper[PartnerReferralsReadErrorBody]] = _PartnerReferralsReadError()
