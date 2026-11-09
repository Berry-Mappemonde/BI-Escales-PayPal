from __future__ import annotations

from typing import TypeAlias

from ..bad_request_error import BadRequestError, BadRequestErrorDict
from ..internal_server_error import InternalServerError, InternalServerErrorDict
from ..not_authorized_error import NotAuthorizedError, NotAuthorizedErrorDict
from ..not_found_error import NotFoundError, NotFoundErrorDict
from ..resource_conflict_error import ResourceConflictError, ResourceConflictErrorDict
from ..service_unavailable_error import ServiceUnavailableError, ServiceUnavailableErrorDict
from ..unauthorized_error import UnauthorizedError, UnauthorizedErrorDict
from ..unprocessable_entity_error import UnprocessableEntityError, UnprocessableEntityErrorDict
from ..unsupported_media_type_error import UnsupportedMediaTypeError, UnsupportedMediaTypeErrorDict

ErrorDefault: TypeAlias = (
    BadRequestError
    | UnauthorizedError
    | NotAuthorizedError
    | NotFoundError
    | ResourceConflictError
    | UnsupportedMediaTypeError
    | UnprocessableEntityError
    | InternalServerError
    | ServiceUnavailableError
)
"""The default error response."""

ErrorDefaultDict: TypeAlias = (
    BadRequestErrorDict
    | UnauthorizedErrorDict
    | NotAuthorizedErrorDict
    | NotFoundErrorDict
    | ResourceConflictErrorDict
    | UnsupportedMediaTypeErrorDict
    | UnprocessableEntityErrorDict
    | InternalServerErrorDict
    | ServiceUnavailableErrorDict
)
