"""Which paths the single-page app knows, and what the other paths do.

Mirrors ``frontend/src/Root.tsx``: the map at ``/``, the wishlist page, and the
two project onboarding pages (the second one is where PayPal sends a project
back after it signs up).

No address answers 404 with the page: links already shared (old ``/en`` and
``/fr`` addresses, or any path the app does not have) must keep working.

- ``/en/...`` and ``/fr/...`` move permanently (301) to the same page with
  ``?lang=``, which is how the app picks its language.
- Any other unknown path moves (302) to the map at ``/``, query string kept, so
  one page is never served under many addresses.

Each known page also gets its own canonical address and hreflang alternates
(``page_head``), instead of every page and language declaring ``/``.
"""
from __future__ import annotations

import html
import re
from typing import Optional
from urllib.parse import parse_qsl, urlencode

_WISHLISTS = "escales/wishlists"
_ONBOARDING = re.compile(r"^projects/[^/]+/onboarding(/return)?$")
_LANG_PREFIX = re.compile(r"^(en|fr)(?:/(.*))?$", re.IGNORECASE)
_LANGS = ("en", "fr")


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


def client_redirect(full_path: str, query: str = "") -> Optional[tuple[str, int]]:
    """Where an address the app does not serve should go, as ``(location, status)``.

    ``None`` for a path the app serves. A language prefix keeps the rest of the
    path when the app knows it, and becomes ``?lang=``.
    """
    path = normalize_client_path(full_path)
    prefixed = _LANG_PREFIX.match(path)
    if not prefixed and is_known_client_route(path):
        return None
    params = parse_qsl(query or "", keep_blank_values=True)
    if prefixed:
        lang = prefixed.group(1).lower()
        rest = normalize_client_path(prefixed.group(2) or "")
        target = "/" + rest if rest and is_known_client_route(rest) else "/"
        params = [("lang", lang)] + [(key, value) for key, value in params if key != "lang"]
        status = 301
    else:
        target = "/"
        status = 302
    return (target + ("?" + urlencode(params) if params else "")), status


def page_lang(query: str = "") -> str:
    """The page's language from ``?lang=``, as the app reads it; English otherwise."""
    for key, value in parse_qsl(query or "", keep_blank_values=True):
        if key == "lang" and value.strip().lower() in _LANGS:
            return value.strip().lower()
    return "en"


_CANONICAL = re.compile(r'<link rel="canonical" href="(https?://[^/"]+)/[^"]*" />')
_ALTERNATES = re.compile(r'[ \t]*<link rel="alternate" hreflang="[^"]+" href="[^"]*" />\n')
_OG_URL = re.compile(r'<meta property="og:url" content="[^"]*" />')
_HTML_LANG = re.compile(r'<html lang="[^"]*">')
_OG_LOCALE = re.compile(r'<meta property="og:locale" content="[^"]*" />')
_OG_LOCALE_ALT = re.compile(r'<meta property="og:locale:alternate" content="[^"]*" />')
_LOCALES = {"en": "en_US", "fr": "fr_FR"}


def page_head(index_html: str, full_path: str, query: str = "") -> str:
    """``index.html`` with the canonical, hreflang, og:url and lang of this page and language.

    English is the default page (``/path``); French is ``/path?lang=fr``. Each
    alternate is its own canonical address. Unchanged if the file has no
    canonical link to start from.
    """
    found = _CANONICAL.search(index_html)
    if not found:
        return index_html
    site = found.group(1)
    path = normalize_client_path(full_path)
    base = f"{site}/{path}" if path else f"{site}/"
    lang = page_lang(query)
    address = {"en": base, "fr": f"{base}?lang=fr"}
    canonical = html.escape(address[lang], quote=True)
    alternates = "".join(
        f'    <link rel="alternate" hreflang="{code}" href="{html.escape(href, quote=True)}" />\n'
        for code, href in (("en", address["en"]), ("fr", address["fr"]), ("x-default", address["en"]))
    )
    out = _ALTERNATES.sub("", index_html)
    out = _CANONICAL.sub(lambda _m: f'<link rel="canonical" href="{canonical}" />\n{alternates.rstrip(chr(10))}', out, count=1)
    out = _OG_URL.sub(f'<meta property="og:url" content="{canonical}" />', out, count=1)
    out = _HTML_LANG.sub(f'<html lang="{lang}">', out, count=1)
    other = "fr" if lang == "en" else "en"
    out = _OG_LOCALE.sub(f'<meta property="og:locale" content="{_LOCALES[lang]}" />', out, count=1)
    out = _OG_LOCALE_ALT.sub(f'<meta property="og:locale:alternate" content="{_LOCALES[other]}" />', out, count=1)
    return out
