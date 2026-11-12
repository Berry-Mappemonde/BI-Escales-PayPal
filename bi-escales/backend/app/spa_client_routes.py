"""The page head for each page and language.

Which paths are pages and where old ``/en``, ``/fr`` and unknown links go is
decided in ``app.main`` (``language_or_unknown_redirect``, #272). This module
only writes, for a page that is served, its own canonical address and hreflang
alternates (``page_head``), instead of every page and language declaring ``/``.
"""
from __future__ import annotations

import html
import re
from urllib.parse import parse_qsl

_LANGS = ("en", "fr")


def normalize_client_path(full_path: str) -> str:
    """``/``, ``/escales/wishlists/`` and ``escales/wishlists`` in one form: no outer slashes."""
    return (full_path or "").strip().strip("/")


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


def page_head(index_html: str, full_path: str, query: str = "", *, image_origin: str | None = None) -> str:
    """``index.html`` with the canonical, hreflang, og:url and lang of this page and language.

    English is the default page (``/path``); French is ``/path?lang=fr``. Each
    alternate is its own canonical address. Unchanged if the file has no
    canonical link to start from.
    """
    if image_origin:
        image_url = html.escape(image_origin.rstrip("/") + "/og-image.png", quote=True)
        index_html = re.sub(
            r'(<meta (?:property="og:image"|name="twitter:image") content=")[^"]*(" />)',
            lambda match: match.group(1) + image_url + match.group(2),
            index_html,
        )
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
