from __future__ import annotations

from typing import Literal

from pydantic import Field
from typing_extensions import TypedDict

from ..core import SdkBaseModel


class EmailOfAPersonOrbusiness(SdkBaseModel):
    """An email address at which the person or business can be contacted."""

    type_: Literal["CUSTOMER_SERVICE"] = Field(default="CUSTOMER_SERVICE", alias="type")
    """The role of the email address."""

    email: str
    """The internationalized email address.<blockquote><strong>Note:</strong> Up to 64 characters are allowed before and
    255 characters are allowed after the <code>@</code> sign. However, the generally accepted maximum length for an
    email address is 254 characters. The pattern verifies that an unquoted <code>@</code> sign exists.</blockquote>"""


class EmailOfAPersonOrbusinessDict(TypedDict):
    type_: Literal["CUSTOMER_SERVICE"]
    email: str
