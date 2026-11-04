"""Configuration from the environment. Sandbox is the only allowed PayPal environment."""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass

SANDBOX_BASE = "https://api-m.sandbox.paypal.com"
AUTH_MAX_DAYS = 29

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class EscalesConfig:
    client_id: str
    client_secret: str
    base_url: str = SANDBOX_BASE
    currency: str = "EUR"
    env: str = "sandbox"

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


def escales_enabled() -> bool:
    return os.environ.get("ESCALES_ENABLED", "").strip().lower() in _TRUTHY


def escales_env() -> str:
    """``development`` unless ``ESCALES_ENV`` says otherwise."""
    raw = (os.environ.get("ESCALES_ENV") or "development").strip().lower()
    return raw or "development"


# Départ d'horloge du mini-mix quand ESCALES_CLOCK_START est absent.
PRODUCTION_CLOCK_START = "2026-11-12"


def _clock_date(raw: str) -> str:
    """Date UTC. Même repli ``Z`` que ``payment_mode._parse_arrival``."""
    text = raw.strip()
    if len(text) == 10 and "T" not in text:
        try:
            return dt.date.fromisoformat(text).isoformat()
        except ValueError as exc:
            raise ValueError("ESCALES_CLOCK_START must be a date (YYYY-MM-DD)") from exc
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("ESCALES_CLOCK_START must be a date (YYYY-MM-DD)") from exc
    if moment.tzinfo is not None:
        moment = moment.astimezone(dt.timezone.utc)
    return moment.date().isoformat()


def clock_start() -> str:
    """Origine de l'horloge de voyage (``YYYY-MM-DD``).

    ``ESCALES_CLOCK_START`` la fixe en développement et dans les tests.
    Sans variable, et en production (``ESCALES_ENV=production``), le départ
    est le 12 novembre 2026. Sans variable hors production, même date.
    """
    raw = (os.environ.get("ESCALES_CLOCK_START") or "").strip()
    if raw:
        return _clock_date(raw)
    # ``ESCALES_ENV=production`` sans variable : 2026-11-12.
    # Développement et tests : la même date, déplaçable avec ESCALES_CLOCK_START.
    return PRODUCTION_CLOCK_START


def limits_enabled() -> bool:
    """IP rate limit and LLM daily cap. On in production only.

    ``ESCALES_RATE_LIMIT_ENABLED`` overrides ``ESCALES_ENV`` when it is set.
    Development, tests, and an empty environment do not limit LLM usage.
    """
    override = (os.environ.get("ESCALES_RATE_LIMIT_ENABLED") or "").strip().lower()
    if override in _TRUTHY:
        return True
    if override in _FALSY:
        return False
    return escales_env() == "production"


def toolkit_enabled() -> bool:
    """PayPal Agent Toolkit. Off unless ESCALES_TOOLKIT_ENABLED is truthy."""
    return os.environ.get("ESCALES_TOOLKIT_ENABLED", "").strip().lower() in _TRUTHY


def naviguide_bridge_enabled() -> bool:
    return os.environ.get("ESCALES_NAVIGUIDE_ENABLED", "").strip().lower() in _TRUTHY


def elastic_evidence_enabled() -> bool:
    return os.environ.get("ESCALES_ELASTIC_ENABLED", "").strip().lower() in _TRUTHY


def kernel_evidence_enabled() -> bool:
    return os.environ.get("ESCALES_KERNEL_ENABLED", "").strip().lower() in _TRUTHY


def channel3_enabled() -> bool:
    return os.environ.get("ESCALES_CHANNEL3_ENABLED", "").strip().lower() in _TRUTHY


def bryntum_scheduler_enabled() -> bool:
    return os.environ.get("ESCALES_BRYNTUM_ENABLED", "").strip().lower() in _TRUTHY


def naviguide_json_path() -> str:
    return (os.environ.get("ESCALES_NAVIGUIDE_JSON") or "").strip()


def naviguide_api_base() -> str:
    return (os.environ.get("NAVIGUIDE_API_URL") or "http://127.0.0.1:8010").strip().rstrip("/")


def vault_enabled() -> bool:
    """PayPal Vault (setup tokens / vaulted capture). Off unless ESCALES_VAULT_ENABLED is truthy."""
    return os.environ.get("ESCALES_VAULT_ENABLED", "").strip().lower() in _TRUTHY


def vault_return_url() -> str:
    return (os.environ.get("ESCALES_VAULT_RETURN_URL") or "https://example.com/escales/vault/return").strip()


def vault_cancel_url() -> str:
    return (os.environ.get("ESCALES_VAULT_CANCEL_URL") or "https://example.com/escales/vault/cancel").strip()


def webhooks_enabled() -> bool:
    """PayPal inbound webhooks. Off unless ESCALES_WEBHOOKS_ENABLED is truthy."""
    return os.environ.get("ESCALES_WEBHOOKS_ENABLED", "").strip().lower() in _TRUTHY


def zapiper_enabled() -> bool:
    """Optional Zapier forwarding hooks. Off unless ESCALES_ZAPIER_ENABLED is truthy."""
    return os.environ.get("ESCALES_ZAPIER_ENABLED", "").strip().lower() in _TRUTHY


def paypal_webhook_id() -> str:
    return (os.environ.get("PAYPAL_WEBHOOK_ID") or "").strip()


def load_config() -> EscalesConfig:
    env = (os.environ.get("PAYPAL_ENV") or "sandbox").strip().lower()
    if env != "sandbox":
        raise RuntimeError("BI Escales runs on the PayPal sandbox only (PAYPAL_ENV=sandbox).")
    return EscalesConfig(
        client_id=os.environ.get("PAYPAL_CLIENT_ID", ""),
        client_secret=os.environ.get("PAYPAL_CLIENT_SECRET", ""),
        env=env,
    )


def membership_url() -> str:
    return (os.environ.get("HELLOASSO_MEMBERSHIP_URL") or "").strip()
