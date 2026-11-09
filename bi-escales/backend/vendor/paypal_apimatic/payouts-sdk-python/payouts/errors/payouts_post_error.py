from __future__ import annotations

from dataclasses import dataclass
from typing import Final, TypeAlias

from ..core import ErrorMapper, RawError, decode_json
from ..models.error import Error

PayoutsPostErrorBody: TypeAlias = Error | RawError


@dataclass(frozen=True, slots=True)
class _PayoutsPostError:
    def map(self, status_code: int, content: bytes) -> PayoutsPostErrorBody:
        match status_code:
            case 400 | 403 | 500:
                return decode_json[Error](content)
            case _:
                return RawError(status_code, content)


payouts_post_error_mapper: Final[ErrorMapper[PayoutsPostErrorBody]] = _PayoutsPostError()
