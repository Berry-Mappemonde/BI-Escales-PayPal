from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..core import UNSET, Optional, SdkBaseModel
from .enums.method import MethodOrStr


class LinkDescription(SdkBaseModel):
    """The request-related `HATEOAS link </docs/api/reference/api-responses/#hateoas-links>`__ information."""

    href: str
    """The complete target URL. To make the related call, combine the method with this `URI Template-formatted
    <https://tools.ietf.org/html/rfc6570>`__ link. For pre-processing, include the ``$``, ``(``, and ``)`` characters.
    The ``href`` is the key HATEOAS component that links a completed call with a subsequent call."""

    rel: str
    """The `link relation type <https://tools.ietf.org/html/rfc5988#section-4>`__, which serves as an ID for a link that
    unambiguously describes the semantics of the link. See `Link Relations
    <https://www.iana.org/assignments/link-relations/link-relations.xhtml>`__."""

    method: Optional[MethodOrStr] = UNSET
    """The HTTP method required to make the related call."""


class LinkDescriptionDict(TypedDict):
    href: str
    rel: str
    method: NotRequired[MethodOrStr]
