from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel


class AddressDetails(SdkBaseModel):
    """The non-portable additional address details that are sometimes needed for compliance, risk, or other scenarios
    where fine-grain address information might be needed. Not portable with common third party and open source.
    Redundant with core fields.<br/>For example, ``address_portable.address_line_1`` is usually a combination of
    ``address_details.street_number``, ``street_name``, and ``street_type``."""

    street_number: Optional[str] = UNSET
    """The street number."""

    street_name: Optional[str] = UNSET
    """The street name. Just ``Drury`` in ``Drury Lane``."""

    street_type: Optional[str] = UNSET
    """The street type. For example, avenue, boulevard, road, or expressway."""

    delivery_service: Optional[str] = UNSET
    """The delivery service. Post office box, bag number, or post office name."""

    building_name: Optional[str] = UNSET
    """A named locations that represents the premise. Usually a building name or number or collection of buildings with
    a common name or number. For example, <code>Craven House</code>."""

    sub_building: Optional[str] = UNSET
    """The first-order entity below a named building or location that represents the sub-premise. Usually a single
    building within a collection of buildings with a common name. Can be a flat, story, floor, room, or apartment."""


class AddressDetailsDict(TypedDict):
    street_number: NotRequired[str]
    street_name: NotRequired[str]
    street_type: NotRequired[str]
    delivery_service: NotRequired[str]
    building_name: NotRequired[str]
    sub_building: NotRequired[str]
