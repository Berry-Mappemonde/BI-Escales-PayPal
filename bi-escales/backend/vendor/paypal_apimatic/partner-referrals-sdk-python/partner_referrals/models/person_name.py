from __future__ import annotations

from typing import Literal

from pydantic import Field
from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel


class PersonName(SdkBaseModel):
    prefix: Optional[str] = UNSET
    """The prefix, or title, to the party's name."""

    given_name: Optional[str] = UNSET
    """When the party is a person, the party's given, or first, name."""

    surname: Optional[str] = UNSET
    """When the party is a person, the party's surname or family name. Also known as the last name. Required when the
    party is a person. Use also to store multiple surnames including the matronymic, or mother's, surname."""

    middle_name: Optional[str] = UNSET
    """When the party is a person, the party's middle name. Use also to store multiple middle names including the
    patronymic, or father's, middle name."""

    suffix: Optional[str] = UNSET
    """The suffix for the party's name."""

    full_name: Optional[str] = UNSET
    """When the party is a person, the party's full name."""

    type_: Literal["LEGAL"] = Field(default="LEGAL", alias="type")
    """The person's name type."""


class PersonNameDict(TypedDict):
    prefix: NotRequired[str]
    given_name: NotRequired[str]
    surname: NotRequired[str]
    middle_name: NotRequired[str]
    suffix: NotRequired[str]
    full_name: NotRequired[str]
    type_: Literal["LEGAL"]
