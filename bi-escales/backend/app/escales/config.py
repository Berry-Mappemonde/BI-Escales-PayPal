"""Configuration from the environment. Sandbox is the only allowed PayPal environment."""
from __future__ import annotations

import os
from dataclasses import dataclass

SANDBOX_BASE = "https://api-m.sandbox.paypal.com"
AUTH_MAX_DAYS = 29

_TRUTHY = {"1", "true", "yes", "on"}


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


def toolkit_enabled() -> bool:
    """PayPal Agent Toolkit. Off unless ESCALES_TOOLKIT_ENABLED is truthy."""
    return os.environ.get("ESCALES_TOOLKIT_ENABLED", "").strip().lower() in _TRUTHY


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
