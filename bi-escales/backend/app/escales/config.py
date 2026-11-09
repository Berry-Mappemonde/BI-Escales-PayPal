"""Configuration from the environment. Sandbox is the only allowed PayPal environment."""
from __future__ import annotations

import datetime as dt
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

SANDBOX_BASE = "https://api-m.sandbox.paypal.com"
AUTH_MAX_DAYS = 29
log = logging.getLogger("escales.config")
_TORONTO = ZoneInfo("America/Toronto")

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
    """Civil date in America/Toronto. A bare ``YYYY-MM-DD`` is kept as written.

    A bad value does not raise: the voyage falls back to 12 November 2026.
    """
    text = raw.strip()
    if len(text) == 10 and "T" not in text:
        try:
            return dt.date.fromisoformat(text).isoformat()
        except ValueError:
            log.warning("ESCALES_CLOCK_START is not a date; using %s", PRODUCTION_CLOCK_START)
            return PRODUCTION_CLOCK_START
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        log.warning("ESCALES_CLOCK_START is not a date; using %s", PRODUCTION_CLOCK_START)
        return PRODUCTION_CLOCK_START
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_TORONTO)
    else:
        moment = moment.astimezone(_TORONTO)
    return moment.date().isoformat()


def simulated_now() -> dt.datetime:
    """Instant of the voyage clock, UTC.

    ``ESCALES_CLOCK_NOW`` moves it in development and in tests. A bare
    ``YYYY-MM-DD`` is 08:00 UTC, the same hour as the voyage origin.
    With no variable, the clock is the real UTC time.
    """
    raw = (os.environ.get("ESCALES_CLOCK_NOW") or "").strip()
    if not raw:
        return dt.datetime.now(dt.timezone.utc)
    return parse_clock_moment(raw)


def clock_now_pinned() -> bool:
    """True when ``ESCALES_CLOCK_NOW`` pins the simulated clock (tests / dev)."""
    return bool((os.environ.get("ESCALES_CLOCK_NOW") or "").strip())


def parse_clock_moment(raw: str) -> dt.datetime:
    """Parse an ISO instant the same way as ``ESCALES_CLOCK_NOW``."""
    text = (raw or "").strip()
    if len(text) == 10 and "T" not in text:
        text = f"{text}T08:00:00+00:00"
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        log.warning("clock moment is not a time; using UTC now")
        return dt.datetime.now(dt.timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.astimezone(dt.timezone.utc)


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


def wishlists_enabled() -> bool:
    """Channel3 wishlists + catalogue API (C3-05). Off unless explicitly enabled."""
    return os.environ.get("ESCALES_WISHLISTS_ENABLED", "").strip().lower() in _TRUTHY


def channel3_api_key() -> str:
    return (os.environ.get("CHANNEL3_API_KEY") or os.environ.get("ESCALES_CHANNEL3_API_KEY") or "").strip()


def channel3_mcp_url() -> str:
    raw = (os.environ.get("CHANNEL3_MCP_URL") or "https://ucp.trychannel3.com/mcp").strip()
    return raw or "https://ucp.trychannel3.com/mcp"


def bryntum_scheduler_enabled() -> bool:
    return os.environ.get("ESCALES_BRYNTUM_ENABLED", "").strip().lower() in _TRUTHY


def naviguide_json_path() -> str:
    return (os.environ.get("ESCALES_NAVIGUIDE_JSON") or "").strip()


def naviguide_api_base() -> str:
    return (os.environ.get("NAVIGUIDE_API_URL") or "http://127.0.0.1:8010").strip().rstrip("/")


def vault_enabled() -> bool:
    """PayPal Vault (setup tokens / vaulted capture). Off unless ESCALES_VAULT_ENABLED is truthy."""
    return os.environ.get("ESCALES_VAULT_ENABLED", "").strip().lower() in _TRUTHY


def demo_treasurer_enabled() -> bool:
    """Sandbox-only, read-only treasurer view without x-admin-key.

    Requires ``ESCALES_DEMO_TREASURER``, ``PAYPAL_ENV=sandbox`` and ``ESCALES_ENV`` other
    than ``production``. It only unlocks a redacted ``GET /pledges`` (no contributor names);
    capture, void and captain-review approval always need the treasurer key.
    """
    if os.environ.get("ESCALES_DEMO_TREASURER", "").strip().lower() not in _TRUTHY:
        return False
    if escales_env() == "production":
        return False
    env = (os.environ.get("PAYPAL_ENV") or "sandbox").strip().lower()
    return env == "sandbox"


def demo_treasurer_flag_set() -> bool:
    return os.environ.get("ESCALES_DEMO_TREASURER", "").strip().lower() in _TRUTHY


def demo_treasurer_env_forbidden() -> bool:
    """Demo flag is on but PAYPAL_ENV is not sandbox or ESCALES_ENV is production."""
    return demo_treasurer_flag_set() and not demo_treasurer_enabled()


def card_fields_enabled() -> bool:
    """JS SDK Card Fields and card payment_source on orders/setup tokens. Off by default."""
    return os.environ.get("ESCALES_CARD_FIELDS_ENABLED", "").strip().lower() in _TRUTHY


def vault_on_purchase_enabled() -> bool:
    """Save the payer method during an AUTHORIZE checkout (store_in_vault ON_SUCCESS). Off by default."""
    return os.environ.get("ESCALES_VAULT_ON_PURCHASE_ENABLED", "").strip().lower() in _TRUTHY


def wallet_pay_enabled() -> bool:
    """Apple Pay and Google Pay SDK components. Off by default; needs sandbox domain registration."""
    return os.environ.get("ESCALES_WALLET_PAY_ENABLED", "").strip().lower() in _TRUTHY


def platform_fees_enabled() -> bool:
    """Multiparty marina platform fees (berth only). Off until Platform partner-referrals ACTIVE."""
    return os.environ.get("ESCALES_PLATFORM_FEES_ENABLED", "").strip().lower() in _TRUTHY


def platform_fee_eur() -> str:
    raw = (os.environ.get("ESCALES_PLATFORM_FEE_EUR") or "3.00").strip().replace(",", ".")
    return raw or "3.00"


def platform_payee_merchant_id() -> str:
    """PayPal merchant id receiving the platform fee (marina multiparty)."""
    return (os.environ.get("ESCALES_PLATFORM_PAYEE_MERCHANT_ID") or "").strip()


def marina_seller_merchant_id(_target_id: str = "") -> str:
    """Marina seller merchant id (from partner-referrals onboarding)."""
    return (os.environ.get("ESCALES_MARINA_SELLER_MERCHANT_ID") or "").strip()


def marina_payout_email_default() -> str:
    return (os.environ.get("ESCALES_MARINA_PAYOUT_EMAIL") or "").strip()


def marina_payouts_enabled() -> bool:
    """Pay marina net via Payouts API on berth capture when multiparty fees are off.

    Off by default like every other ESCALES_*_ENABLED flag; test2 sets it to 1 explicitly.
    """
    return os.environ.get("ESCALES_MARINA_PAYOUTS_ENABLED", "").strip().lower() in _TRUTHY


def paypal_berth_platform_fees_on_order(target_id: str = "") -> bool:
    """True when PayPal Orders v2 will carry multiparty platform_fees for this berth."""
    if not platform_fees_enabled():
        return False
    return bool(marina_seller_merchant_id(target_id)) and bool(platform_payee_merchant_id())


def apple_pay_domain_association_file() -> str:
    """Optional override path to the Apple Pay domain association file."""
    return (os.environ.get("ESCALES_APPLE_PAY_DOMAIN_ASSOCIATION_FILE") or "").strip()


def bundled_apple_pay_domain_association_path() -> Path:
    """PayPal sandbox association file shipped under backend/static/.well-known/."""
    backend_root = Path(__file__).resolve().parents[2]
    return backend_root / "static" / ".well-known" / "apple-developer-merchantid-domain-association"


def resolve_apple_pay_domain_association_path() -> Path:
    override = apple_pay_domain_association_file()
    if override:
        return Path(override).expanduser().resolve()
    return bundled_apple_pay_domain_association_path()


def vault_return_url() -> str:
    default = f"{public_base_url()}/?vault=return"
    return (os.environ.get("ESCALES_VAULT_RETURN_URL") or default).strip()


def vault_cancel_url() -> str:
    default = f"{public_base_url()}/?vault=cancel"
    return (os.environ.get("ESCALES_VAULT_CANCEL_URL") or default).strip()


# Same Render service that serves the built frontend. The static host 404s.
_DEFAULT_ORDER_RETURN = "https://bi-escales-api.onrender.com/?paypal=return"
_DEFAULT_ORDER_CANCEL = "https://bi-escales-api.onrender.com/?paypal=cancel"


def order_return_url() -> str:
    """Where PayPal sends the buyer after approving a classic AUTHORIZE order."""
    return (os.environ.get("ESCALES_RETURN_URL") or _DEFAULT_ORDER_RETURN).strip()


def order_cancel_url() -> str:
    """Where PayPal sends the buyer if they cancel a classic AUTHORIZE order."""
    return (os.environ.get("ESCALES_CANCEL_URL") or _DEFAULT_ORDER_CANCEL).strip()


def subscription_return_url() -> str:
    """Crew supporter subscription approval return (PayPal billing subscribe)."""
    default = f"{public_base_url()}/?sub=return"
    return (os.environ.get("ESCALES_SUBSCRIPTION_RETURN_URL") or default).strip()


def subscription_cancel_url() -> str:
    """Crew supporter subscription checkout cancel."""
    default = f"{public_base_url()}/?sub=cancel"
    return (os.environ.get("ESCALES_SUBSCRIPTION_CANCEL_URL") or default).strip()


def webhooks_enabled() -> bool:
    """PayPal inbound webhooks. Off unless ESCALES_WEBHOOKS_ENABLED is truthy."""
    return os.environ.get("ESCALES_WEBHOOKS_ENABLED", "").strip().lower() in _TRUTHY


def zapiper_enabled() -> bool:
    """Optional Zapier forwarding hooks. Off unless ESCALES_ZAPIER_ENABLED is truthy."""
    return os.environ.get("ESCALES_ZAPIER_ENABLED", "").strip().lower() in _TRUTHY


def paypal_webhook_id() -> str:
    return (os.environ.get("PAYPAL_WEBHOOK_ID") or "").strip()


PUBLIC_API_ORIGIN = "https://bi-escales-api.onrender.com"
PAYPAL_WEBHOOK_PATH = "/api/escales/webhooks/paypal"
# Vite dev server, plus the Render service that serves this API and the page.
_DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    PUBLIC_API_ORIGIN,
)


def public_base_url() -> str:
    """Origin PayPal and the browser use to reach this API. No trailing slash."""
    raw = (os.environ.get("ESCALES_PUBLIC_URL") or PUBLIC_API_ORIGIN).strip().rstrip("/")
    return raw or PUBLIC_API_ORIGIN


def paypal_webhook_url() -> str:
    """URL to register in the PayPal sandbox webhook dashboard."""
    return f"{public_base_url()}{PAYPAL_WEBHOOK_PATH}"


def cors_origins() -> list[str]:
    """Browser origins allowed to call the API.

    ``ESCALES_CORS_ORIGINS`` is a comma-separated extra list. The mini-mix
    Vite origin is always included.
    """
    origins = list(_DEFAULT_CORS_ORIGINS)
    extra = os.environ.get("ESCALES_CORS_ORIGINS") or ""
    for part in extra.split(","):
        origin = part.strip().rstrip("/")
        if origin and origin not in origins:
            origins.append(origin)
    return origins


def load_config() -> EscalesConfig:
    env = (os.environ.get("PAYPAL_ENV") or "sandbox").strip().lower()
    if env != "sandbox":
        raise RuntimeError("BI Escales runs on the PayPal sandbox only (PAYPAL_ENV=sandbox).")
    return EscalesConfig(
        client_id=os.environ.get("PAYPAL_CLIENT_ID", ""),
        client_secret=os.environ.get("PAYPAL_CLIENT_SECRET", ""),
        env=env,
    )