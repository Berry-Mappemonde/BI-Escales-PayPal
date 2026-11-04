"""Noms d'escale montrés au lecteur.

Reprend le title-case par tirets de ``captain.display_name`` et le repli
d'accents de ``naviguide_bridge._slug`` (lui-même copié de
``escale_watch.slug``). Le préfixe ``dep-`` est l'identifiant de jalon,
jamais le nom affiché. Les graphies que ce title-case ne peut pas
reconstruire sont celles déjà écrites dans NAVIGUIDE.
"""
from __future__ import annotations

import re

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_FOLD = str.maketrans("àâäáéèêëíìîïóòôöúùûüçñ", "aaaaeeeeiiiioooouuuucn")

# Graphies déjà présentes dans NAVIGUIDE (fixtures, domaines de port, horaire local).
ESCALE_DISPLAY_NAMES = {
    "pointe-a-pitre": "Pointe-à-Pitre",
    "fort-de-france": "Fort-de-France",
    "la-rochelle": "La Rochelle",
    "noumea": "Nouméa",
}


def _slug(value: str) -> str:
    folded = (value or "").strip().lower().translate(_FOLD)
    text = _SLUG_RE.sub("-", folded).strip("-")
    while text.startswith("dep-"):
        text = text[4:]
    return text


def _title_slug(slug: str) -> str:
    """Même découpage que l'ancien ``captain.display_name``."""
    return "-".join(
        (part[:1].upper() + part[1:]) if part else part
        for part in slug.split("-")
    )


def display_name(escale_id: str) -> str:
    """Nom lisible. ``dep-fort-de-france`` devient ``Fort-de-France``."""
    raw = "" if escale_id is None else str(escale_id).strip()
    if not raw:
        return ""
    slug = _slug(raw)
    if not slug:
        return ""
    known = ESCALE_DISPLAY_NAMES.get(slug)
    if known:
        return known
    return _title_slug(slug)
