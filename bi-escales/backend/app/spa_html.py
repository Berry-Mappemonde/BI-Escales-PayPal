"""Server-side SPA index.html tweaks (lang + share meta for crawlers)."""
from __future__ import annotations

import re

from app.spa_client_routes import normalize_client_path

SITE_ORIGIN = "https://escales.naviguide.fr"

_HEAD_COPY: dict[str, dict[str, str]] = {
    "en": {
        "title": "BI Escales — Pay only when we arrive",
        "description": (
            "BI Escales — support the Berry-Mappemonde expedition. "
            "Stop pledges capture on boat arrival (voided if the stop is cancelled); "
            "cabins on leg departure; common fund and project gifts at once."
        ),
        "og_locale": "en_US",
        "canonical_suffix": "",
    },
    "fr": {
        "title": "BI Escales — Payez seulement à notre arrivée",
        "description": (
            "BI Escales — soutenez l'expédition Berry-Mappemonde. "
            "Promesses escale encaissées à l'arrivée du bateau (annulées si l'escale est annulée) ; "
            "cabines au départ de l'étape ; fonds commun et dons projet immédiatement."
        ),
        "og_locale": "fr_FR",
        "canonical_suffix": "/fr",
    },
}


def spa_locale_from_path(full_path: str) -> str:
    """Default EN for `/` and unknown soft-404 shells (jury default)."""
    norm = normalize_client_path(full_path)
    if norm == "fr" or norm.startswith("fr/"):
        return "fr"
    return "en"


def _canonical_url(full_path: str) -> str:
    locale = spa_locale_from_path(full_path)
    suffix = _HEAD_COPY[locale]["canonical_suffix"]
    if suffix:
        return f"{SITE_ORIGIN}{suffix}"
    norm = normalize_client_path(full_path)
    if norm == "en":
        return f"{SITE_ORIGIN}/en"
    if norm == "escales/wishlists":
        return f"{SITE_ORIGIN}/escales/wishlists"
    if norm == "en/escales/wishlists":
        return f"{SITE_ORIGIN}/en/escales/wishlists"
    if norm == "fr/escales/wishlists":
        return f"{SITE_ORIGIN}/fr/escales/wishlists"
    return f"{SITE_ORIGIN}/"


def _sub_meta(html: str, *, attr: str, name: str, value: str) -> str:
    pattern = rf'<meta\s+{attr}="{re.escape(name)}"\s+content="[^"]*"\s*/>'
    replacement = f'<meta {attr}="{name}" content="{value}" />'
    return re.sub(pattern, replacement, html, count=1)


def _sub_title(html: str, title: str) -> str:
    return re.sub(r"<title>[^<]*</title>", f"<title>{title}</title>", html, count=1)


def _sub_link_canonical(html: str, href: str) -> str:
    pattern = r'<link\s+rel="canonical"\s+href="[^"]*"\s*/>'
    return re.sub(pattern, f'<link rel="canonical" href="{href}" />', html, count=1)


def _sub_og_url(html: str, url: str) -> str:
    return _sub_meta(html, attr="property", name="og:url", value=url)


def render_spa_html(template: str, full_path: str) -> str:
    locale = spa_locale_from_path(full_path)
    copy = _HEAD_COPY[locale]
    canonical = _canonical_url(full_path)

    html = re.sub(r'<html\s+lang="[^"]*"', f'<html lang="{locale}"', template, count=1)
    html = _sub_title(html, copy["title"])
    html = _sub_meta(html, attr="name", name="description", value=copy["description"])
    html = _sub_meta(html, attr="property", name="og:title", value=copy["title"])
    html = _sub_meta(html, attr="property", name="og:description", value=copy["description"])
    html = _sub_meta(html, attr="property", name="og:locale", value=copy["og_locale"])
    html = _sub_meta(html, attr="name", name="twitter:title", value=copy["title"])
    html = _sub_meta(html, attr="name", name="twitter:description", value=copy["description"])
    html = _sub_link_canonical(html, canonical)
    html = _sub_og_url(html, canonical)

    alternate = "fr_FR" if locale == "en" else "en_US"
    html = _sub_meta(html, attr="property", name="og:locale:alternate", value=alternate)

    return html
