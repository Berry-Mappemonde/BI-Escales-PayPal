"""App UI languages discovered from frontend i18n locale files."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

_LOCALES_DIR = Path(__file__).resolve().parents[3] / "frontend" / "src" / "i18n" / "locales"


@lru_cache(maxsize=1)
def app_language_codes() -> tuple[str, ...]:
    if not _LOCALES_DIR.is_dir():
        return ("fr",)
    codes = tuple(sorted(path.stem for path in _LOCALES_DIR.glob("*.json") if path.is_file()))
    return codes if codes else ("fr",)


def default_app_language() -> str:
    codes = app_language_codes()
    if "fr" in codes:
        return "fr"
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
    """Unknown or empty language falls back to the default app language."""
    return forced_app_lang(lang) or default_app_language()


def resolve_app_language(requested: Optional[str]) -> str:
    """Language selected in the app UI. Ignores message text and Accept-Language."""
    if (requested or "").strip():
        return normalize_app_lang(requested)
    return default_app_language()


_ERROR_TEXT: dict[str, dict[str, str]] = {
    "admin_key_required": {
        "en": "Admin key required",
        "fr": "Clé trésorier requise",
    },
    "admin_key_rejected": {
        "en": "Admin key rejected",
        "fr": "Clé trésorier refusée",
    },
    "admin_key_not_configured": {
        "en": "ESCALES_ADMIN_KEY is not configured",
        "fr": "ESCALES_ADMIN_KEY n'est pas configurée",
    },
    "paypal_not_configured": {
        "en": "PayPal sandbox is not configured",
        "fr": "Le bac à sable PayPal n'est pas configuré",
    },
    "pledge_not_found": {
        "en": "Pledge not found",
        "fr": "Promesse introuvable",
    },
    "order_not_approved": {
        "en": "order not approved yet",
        "fr": "commande pas encore approuvée",
    },
    "project_pledge_min_amount": {
        "en": "Project donations must be at least 1.00 EUR",
        "fr": "Le don à un projet doit être d'au moins 1,00 €",
    },
    "amount_invalid": {
        "en": "amount_eur must be a positive amount with at most 2 decimal places",
        "fr": "Le montant doit être positif avec au plus 2 décimales",
    },
    "kind_invalid": {
        "en": "kind must be one of the supported pledge kinds",
        "fr": "Le type de promesse n'est pas reconnu",
    },
    "missing_field": {
        "en": "A required field is missing",
        "fr": "Un champ obligatoire est manquant",
    },
    "validation_error": {
        "en": "Invalid request",
        "fr": "Requête invalide",
    },
    "paypal_request_failed": {
        "en": "PayPal request failed",
        "fr": "Échec de la requête PayPal",
    },
}


def error_text(code: str, lang: Optional[str] = None, **fmt: Any) -> str:
    """Localized user-facing error string for a machine-readable code."""
    app_lang = normalize_app_lang(lang)
    table = _ERROR_TEXT.get(code) or _ERROR_TEXT["validation_error"]
    text = table.get(app_lang) or table.get("en") or code
    if fmt:
        try:
            return text.format(**fmt)
        except (KeyError, ValueError):
            return text
    return text


def error_payload(code: str, lang: Optional[str] = None, **fmt: Any) -> dict[str, str]:
    return {"code": code, "detail": error_text(code, lang, **fmt)}


def validation_code_from_message(message: str) -> Optional[str]:
    msg = (message or "").strip()
    if not msg:
        return None
    if msg == "Admin key required":
        return "admin_key_required"
    if msg == "Admin key rejected":
        return "admin_key_rejected"
    if msg == "ESCALES_ADMIN_KEY is not configured":
        return "admin_key_not_configured"
    if msg == "PayPal sandbox is not configured":
        return "paypal_not_configured"
    if msg == "Pledge not found":
        return "pledge_not_found"
    if msg == "order not approved yet":
        return "order_not_approved"
    if msg == "amount_eur must be a positive amount with at most 2 decimal places":
        return "amount_invalid"
    if msg.startswith("kind must be one of:"):
        return "kind_invalid"
    if re.match(r"^project_pledge amount must be at least [\d.]+\s+EUR$", msg):
        return "project_pledge_min_amount"
    if re.match(r"^[a-z_]+ amount must be at least ", msg):
        return "validation_error"
    if re.match(r"^[a-z_]+ amount must be [\d.]+\s+EUR$", msg):
        return "validation_error"
    if msg.endswith(" is required"):
        return "missing_field"
    return None
