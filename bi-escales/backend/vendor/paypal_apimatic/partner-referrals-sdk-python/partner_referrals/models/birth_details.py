from __future__ import annotations

from typing_extensions import TypedDict

from ..core import SdkBaseModel


class BirthDetails(SdkBaseModel):
    """Date of birth data provided by the user"""

    date_of_birth: str
    """The stand-alone date, in `Internet date and time format <https://tools.ietf.org/html/rfc3339#section-5.6>`__. To
    represent special legal values, such as a date of birth, you should use dates with no associated time or time-zone
    data. Whenever possible, use the standard ``date_time`` type. This regular expression does not validate all dates.
    For example, February 31 is valid and nothing is known about leap years."""


class BirthDetailsDict(TypedDict):
    date_of_birth: str
