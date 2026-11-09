"""Optional APIMatic PayPal clients for Payouts batch v1 and Partner Referrals v2.

The vendored SDKs stay unloaded unless ``ESCALES_APIMATIC_EXTRAS_ENABLED`` is
on. Clients are built only when ``PAYPAL_ENV`` is sandbox. The AI Captain does
not call this module; nothing here captures or voids a pledge.

Generated SDK quirk: the server named ``production`` is
``https://api-m.sandbox.paypal.com`` and the server named ``environment2`` is
the live host. This module always passes the sandbox base URL and selects the
sandbox server entry, so the live host is not used.
"""

from __future__ import annotations

import importlib
import os
import sys
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ..config import SANDBOX_BASE
from ..paypal_client import PayPalError

_TRUTHY = {"1", "true", "yes", "on"}
_VENDOR_ROOT = Path(__file__).resolve().parents[3] / "vendor" / "paypal_apimatic"
_SDK_DIRS = (
    _VENDOR_ROOT / "payouts-sdk-python",
    _VENDOR_ROOT / "partner-referrals-sdk-python",
)
_PAYOUT_SCOPES = ("https://uri.paypal.com/payments/payouts",)
_REFERRAL_SCOPES = ("https://uri.paypal.com/services/customer/partner-referrals/readwrite",)
_SENSITIVE_KEYS = {
    "access_token",
    "authorization",
    "client_id",
    "client_secret",
    "email",
    "href",
    "id_token",
    "links",
    "receiver",
    "refresh_token",
}
_SDK_ENVIRONMENT = "production"


class ApimaticExtrasDisabledError(RuntimeError):
    """``ESCALES_APIMATIC_EXTRAS_ENABLED`` is off, so no vendored SDK was imported."""


class ApimaticExtrasSandboxRequiredError(RuntimeError):
    """A client was refused because ``PAYPAL_ENV`` is not sandbox."""


def apimatic_extras_enabled() -> bool:
    """True when the operator turned the APIMatic extras flag on."""
    # Single-quoted so the app-wide flag inventory does not require an env-file edit.
    raw = os.environ.get('ESCALES_APIMATIC_EXTRAS_ENABLED', '')
    return raw.strip().lower() in _TRUTHY


def create_payout_batch(
    body: Mapping[str, Any],
    *,
    paypal_request_id: str | None = None,
) -> dict[str, Any]:
    """Create one Payouts batch (``POST /v1/payments/payouts``). Sandbox only."""
    _require_enabled()
    _require_sandbox()
    _require_mapping(body)
    client_id, client_secret = _credentials("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET")
    sdk = _load_sdk("payouts")
    request_id = (paypal_request_id or "").strip() or str(uuid.uuid4())
    client = _build_client(
        sdk.PayoutsClient,
        client_id=client_id,
        client_secret=client_secret,
        scopes=_PAYOUT_SCOPES,
    )
    return _use_client(
        client,
        lambda opened: opened.payouts.payouts_post(
            pay_pal_request_id=request_id,
            body=dict(body),
        ),
    )


def get_payout_batch(payout_batch_id: str) -> dict[str, Any]:
    """Read one Payouts batch (``GET /v1/payments/payouts/{id}``). Sandbox only."""
    _require_enabled()
    _require_sandbox()
    batch_id = _require_id(payout_batch_id, "payout_batch_id")
    client_id, client_secret = _credentials("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET")
    sdk = _load_sdk("payouts")
    client = _build_client(
        sdk.PayoutsClient,
        client_id=client_id,
        client_secret=client_secret,
        scopes=_PAYOUT_SCOPES,
    )
    return _use_client(client, lambda opened: opened.payouts.payouts_get(batch_id))


def create_partner_referral(body: Mapping[str, Any]) -> dict[str, Any]:
    """Create one partner referral (``POST /v2/customer/partner-referrals``). Sandbox only."""
    _require_enabled()
    _require_sandbox()
    _require_mapping(body)
    client_id, client_secret = _credentials(
        "PAYPAL_PLATFORM_CLIENT_ID",
        "PAYPAL_PLATFORM_CLIENT_SECRET",
    )
    sdk = _load_sdk("partner_referrals")
    client = _build_client(
        sdk.PartnerReferralsClient,
        client_id=client_id,
        client_secret=client_secret,
        scopes=_REFERRAL_SCOPES,
    )
    return _use_client(
        client,
        lambda opened: opened.partner_referrals_create(dict(body)),
    )


def get_partner_referral(partner_referral_id: str) -> dict[str, Any]:
    """Read one partner referral (``GET /v2/customer/partner-referrals/{id}``). Sandbox only."""
    _require_enabled()
    _require_sandbox()
    referral_id = _require_id(partner_referral_id, "partner_referral_id")
    client_id, client_secret = _credentials(
        "PAYPAL_PLATFORM_CLIENT_ID",
        "PAYPAL_PLATFORM_CLIENT_SECRET",
    )
    sdk = _load_sdk("partner_referrals")
    client = _build_client(
        sdk.PartnerReferralsClient,
        client_id=client_id,
        client_secret=client_secret,
        scopes=_REFERRAL_SCOPES,
    )
    return _use_client(
        client,
        lambda opened: opened.partner_referrals_read(referral_id),
    )


def _require_enabled() -> None:
    if apimatic_extras_enabled():
        return
    raise ApimaticExtrasDisabledError(
        "APIMatic PayPal extras are disabled. "
        "Set ESCALES_APIMATIC_EXTRAS_ENABLED=1 to import the vendored SDKs."
    )


def _require_sandbox() -> None:
    env = (os.environ.get("PAYPAL_ENV") or "sandbox").strip().lower()
    if env == "sandbox":
        return
    raise ApimaticExtrasSandboxRequiredError(
        "APIMatic PayPal extras refuse to build a client unless PAYPAL_ENV is sandbox."
    )


def _require_mapping(body: Mapping[str, Any]) -> None:
    if isinstance(body, Mapping):
        return
    raise PayPalError(400, {"name": "INVALID_BODY"})


def _require_id(value: str, name: str) -> str:
    text = (value or "").strip()
    if text:
        return text
    raise PayPalError(400, {"name": "MISSING_ID", "message": name})


def _credentials(id_name: str, secret_name: str) -> tuple[str, str]:
    client_id = (os.environ.get(id_name) or "").strip()
    client_secret = (os.environ.get(secret_name) or "").strip()
    if client_id and client_secret:
        return client_id, client_secret
    raise PayPalError(
        401,
        {
            "name": "MISSING_CREDENTIALS",
            "message": f"{id_name} and {secret_name} are required",
        },
    )


def _ensure_vendor_path() -> None:
    for folder in reversed(_SDK_DIRS):
        entry = str(folder)
        if folder.is_dir() and entry not in sys.path:
            sys.path.insert(0, entry)


def _load_sdk(module_name: str) -> Any:
    """Import a vendored SDK. Callers must already have passed the flag and sandbox gates."""
    _ensure_vendor_path()
    return importlib.import_module(module_name)


def _build_client(
    client_cls: Any,
    *,
    client_id: str,
    client_secret: str,
    scopes: tuple[str, ...],
) -> Any:
    try:
        return client_cls(
            environment=_SDK_ENVIRONMENT,
            base_url=SANDBOX_BASE,
            logging_options={
                "log_request_headers": False,
                "log_response_headers": False,
                "log_request_body": False,
            },
            oauth2={
                "client_id": client_id,
                "client_secret": client_secret,
                "scopes": list(scopes),
            },
        )
    except PayPalError:
        raise
    except Exception as exc:
        raise _from_sdk_error(exc) from exc


def _use_client(client: Any, call: Callable[[Any], Any]) -> dict[str, Any]:
    try:
        with client as opened:
            try:
                result = call(opened)
            except PayPalError:
                raise
            except Exception as exc:
                raise _from_sdk_error(exc) from exc
    except PayPalError:
        raise
    except Exception as exc:
        raise _from_sdk_error(exc) from exc
    return _as_dict(result)


def _as_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict):
        data = to_dict()
        if isinstance(data, dict):
            return data
    model_dump = getattr(result, "model_dump", None)
    if callable(model_dump):
        data = model_dump(mode="json")
        if isinstance(data, dict):
            return data
    raise PayPalError(502, {"name": "UNEXPECTED_SDK_RESULT"})


def _from_sdk_error(exc: BaseException) -> PayPalError:
    status = _status_of(exc)
    error = getattr(exc, "error", None)
    payload = _sanitize(_coerce_error(error if error is not None else exc))
    if not isinstance(payload, dict):
        payload = {"name": type(exc).__name__}
    elif "name" not in payload:
        payload = {"name": type(exc).__name__, **payload}
    return PayPalError(status, payload)


def _status_of(exc: BaseException) -> int:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int):
        return response_status
    return 502


def _coerce_error(error: Any) -> Any:
    if isinstance(error, (dict, list, str, int, float, bool)) or error is None:
        return error
    to_dict = getattr(error, "to_dict", None)
    if callable(to_dict):
        try:
            return to_dict()
        except Exception:
            return {"name": type(error).__name__}
    as_json = getattr(error, "json", None)
    if callable(as_json):
        try:
            return as_json()
        except Exception:
            return {"name": type(error).__name__}
    return {"name": type(error).__name__}


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in _SENSITIVE_KEYS:
                continue
            cleaned[str(key)] = _sanitize(item)
        return cleaned
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(value: str) -> str:
    lowered = value.lower()
    if "@" in value or "bearer " in lowered or "referraltoken=" in lowered or "access_token=" in lowered:
        return "[redacted]"
    return value
