"""App UI languages discovered from frontend i18n locale files."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

_LOCALES_DIR = Path(__file__).resolve().parents[3] / "frontend" / "src" / "i18n" / "locales"


@lru_cache(maxsize=1)
def app_language_codes() -> tuple[str, ...]:
    if not _LOCALES_DIR.is_dir():
        return ("en",)
    codes = tuple(sorted(path.stem for path in _LOCALES_DIR.glob("*.json") if path.is_file()))
    return codes if codes else ("en",)


def default_app_language() -> str:
    codes = app_language_codes()
    if "en" in codes:
        return "en"
    return codes[0]


def forced_app_lang(lang: Optional[str]) -> Optional[str]:
    """Map a locale tag to a supported app language, or None when unknown."""
    token = (lang or "").strip().lower()
    if not token:
        return None
    for code in app_language_codes():
        if token == code or token.startswith(f"{code}-"):
            return code
    return None


def normalize_app_lang(lang: Optional[str]) -> str:
    """Unknown or empty language falls back to the default app language (en when present)."""
    return forced_app_lang(lang) or default_app_language()


def resolve_app_language(requested: Optional[str]) -> str:
    """Language selected in the app UI. Ignores message text and Accept-Language."""
    if (requested or "").strip():
        return normalize_app_lang(requested)
    return default_app_language()
