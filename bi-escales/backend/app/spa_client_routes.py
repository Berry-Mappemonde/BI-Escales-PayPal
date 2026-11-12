"""Which paths the single-page app knows, so that an unknown one answers 404.

Mirrors ``frontend/src/Root.tsx``: the map at ``/``, the wishlist page, and the
two project onboarding pages (the second one is where PayPal sends a project
back after it signs up). Every other path still gets the page's HTML, so the
app loads and shows the map, but with status 404 instead of 200: a crawler or
a link checker then knows the address does not exist.
"""
from __future__ import annotations

import re

_WISHLISTS = "escales/wishlists"
_ONBOARDING = re.compile(r"^projects/[^/]+/onboarding(/return)?$")


def normalize_client_path(full_path: str) -> str:
    """``/``, ``/escales/wishlists/`` and ``escales/wishlists`` in one form: no outer slashes."""
    return (full_path or "").strip().strip("/")


def is_known_client_route(full_path: str) -> bool:
    path = normalize_client_path(full_path)
    if path == "":
        return True
    # Root.tsx shows the wishlist page for any path that ends with it.
    if path == _WISHLISTS or path.endswith("/" + _WISHLISTS):
        return True
    return bool(_ONBOARDING.match(path))
