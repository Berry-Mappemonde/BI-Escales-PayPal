"""App language list stays aligned with frontend i18n."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.app_i18n import APP_LANGUAGES, DEFAULT_APP_LANGUAGE, forced_app_lang, normalize_app_lang
from app.escales.captain import resolve_chat_lang


def test_app_languages_match_frontend_i18n():
    assert APP_LANGUAGES == ("en", "fr")
    assert DEFAULT_APP_LANGUAGE == "en"


def test_unknown_language_falls_back_to_en():
    assert normalize_app_lang("de") == "en"
    assert normalize_app_lang("xx") == "en"
    assert forced_app_lang("de") is None


def test_resolve_chat_lang_honours_app_language_over_message():
    french_text = "Je voudrais parrainer 120 milles près d'Ajaccio"
    assert resolve_chat_lang(french_text, requested="en") == "en"
    assert resolve_chat_lang(french_text, requested="de") == "en"
    assert resolve_chat_lang(french_text, requested="fr-FR") == "fr"
