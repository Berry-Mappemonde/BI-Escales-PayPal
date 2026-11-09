from __future__ import annotations

from pydantic import Field
from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.type import TypeOrStr


class BankAccountIdentifier(SdkBaseModel):
    """The bank account ID. An ID with ``ROUTING_NUMBER_1`` is required."""

    type_: Optional[TypeOrStr] = Field(default=UNSET, alias="type")
    """The bank account ID type."""

    value: Optional[str] = UNSET
    """The value of account identifier."""


class BankAccountIdentifierDict(TypedDict):
    type_: NotRequired[TypeOrStr]
    value: NotRequired[str]
