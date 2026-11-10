"""Channel3 product URL rules — never expose the generic marketing homepage as a buy link."""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

_HOMEPAGE = re.compile(r"^https://(?:www\.)?trychannel3\.com/?$", re.IGNORECASE)


def is_absolute_https_url(url: Optional[str]) -> bool:
    token = str(url or "").strip()
    if not token:
        return False
    parsed = urlparse(token)
    return parsed.scheme == "https" and bool(parsed.netloc)


def is_channel3_homepage_url(url: Optional[str]) -> bool:
    token = str(url or "").strip()
    if not token or not is_absolute_https_url(token):
        return False
    return bool(_HOMEPAGE.match(token))


def normalize_channel3_product_url(url: Optional[str]) -> Optional[str]:
    """Return the URL when it is a real product offer; drop homepages and blanks."""
    token = str(url or "").strip()
    if not token or not is_absolute_https_url(token) or is_channel3_homepage_url(token):
        return None
    host = (urlparse(token).hostname or "").casefold()
    if host in {"trychannel3.com", "www.trychannel3.com"}:
        return None
    return token
