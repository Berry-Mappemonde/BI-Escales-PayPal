from __future__ import annotations

from typing import TypeAlias

from ..account_status_error import AccountStatusError, AccountStatusErrorDict
from ..product_ppcp_unauthorized import ProductPpcpUnauthorized, ProductPpcpUnauthorizedDict
from ..user_not_found import UserNotFound, UserNotFoundDict

Detail1: TypeAlias = UserNotFound | AccountStatusError | ProductPpcpUnauthorized

Detail1Dict: TypeAlias = UserNotFoundDict | AccountStatusErrorDict | ProductPpcpUnauthorizedDict
