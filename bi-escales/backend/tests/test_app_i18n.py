"""App language list stays aligned with frontend i18n."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.app_i18n import (
    app_language_codes,
    default_app_language,
    forced_app_lang,
    normalize_app_lang,
)
from app.escales.captain import resolve_chat_lang


def test_app_languages_match_frontend_i18n():
    codes = app_language_codes()
    assert "en" in codes and "fr" in codes
    assert default_app_language() == "fr"


def test_unknown_language_falls_back_to_fr():
    assert normalize_app_lang("de") == "fr"
    assert normalize_app_lang("xx") == "fr"
    assert forced_app_lang("de") is None


def test_resolve_chat_lang_honours_app_language_over_message():
    french_text = "Je voudrais parrainer 120 milles près d'Ajaccio"
    assert resolve_chat_lang(french_text, requested="en") == "en"
    assert resolve_chat_lang(french_text, requested="de") == "fr"
    assert resolve_chat_lang(french_text, requested="fr-FR") == "fr"
    assert resolve_chat_lang(french_text, requested=None) == "fr"
    assert resolve_chat_lang(french_text, accept_language="fr-FR,fr;q=0.9") == "fr"
