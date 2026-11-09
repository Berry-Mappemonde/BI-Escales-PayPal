from __future__ import annotations

from dataclasses import dataclass
from typing import Final, TypeAlias

from ..core import ErrorMapper, RawError, decode_json
from ..models.error import Error

PayoutsGetErrorBody: TypeAlias = Error | RawError


@dataclass(frozen=True, slots=True)
class _PayoutsGetError:
    def map(self, status_code: int, content: bytes) -> PayoutsGetErrorBody:
        match status_code:
            case 404 | 500:
                return decode_json[Error](content)
            case _:
                return RawError(status_code, content)


payouts_get_error_mapper: Final[ErrorMapper[PayoutsGetErrorBody]] = _PayoutsGetError()
