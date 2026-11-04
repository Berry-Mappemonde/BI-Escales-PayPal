"""App UI languages. Keep in sync with frontend/src/i18n/index.ts resource keys."""
from __future__ import annotations

from typing import Optional

# frontend: resources { fr, en }
APP_LANGUAGES: tuple[str, ...] = ("en", "fr")
DEFAULT_APP_LANGUAGE = "en"


def forced_app_lang(lang: Optional[str]) -> Optional[str]:
    """Map a locale tag to a supported app language, or None when unknown."""
    token = (lang or "").strip().lower()
    if not token:
        return None
    for code in APP_LANGUAGES:
        if token == code or token.startswith(f"{code}-"):
            return code
    return None


def normalize_app_lang(lang: Optional[str]) -> str:
    """Unknown or empty language falls back to DEFAULT_APP_LANGUAGE (en)."""
    return forced_app_lang(lang) or DEFAULT_APP_LANGUAGE
