"""Read-only PayPal Server SDK gateway. Sandbox only.

The process keeps one ``PaypalServersdkClient``. ``paypalserversdk`` is imported
inside :func:`build_sandbox_client`, and only when ``ESCALES_PAYPAL_SDK_ENABLED``
is truthy and ``PAYPAL_ENV`` is ``sandbox``.
"""

from __future__ import annotations

import importlib
import os
import threading
from typing import Any, NoReturn

from .config import SANDBOX_BASE, paypal_sdk_reads_enabled

_TIMEOUT_SECONDS = 30
_MAX_RETRIES = 0

_CLIENT: Any = None
_CLIENT_LOCK = threading.Lock()
_API_EXCEPTION: Any = None
_API_HELPER: Any = None


def reset_client() -> None:
    """Drop the cached client. Tests use this between cases."""
    global _CLIENT
    _CLIENT = None


def install_client(sdk: Any) -> None:
    """Use a client built with a stubbed ``requests`` session."""
    global _CLIENT
    _CLIENT = sdk


def _require_sandbox() -> None:
    env = (os.environ.get("PAYPAL_ENV") or "").strip().lower()
    if env != "sandbox":
        raise RuntimeError(
            "PayPal SDK gateway refuses to build unless PAYPAL_ENV=sandbox"
        )


def build_sandbox_client(
    *,
    http_client_instance: Any = None,
    http_call_back: Any = None,
) -> Any:
    """Build a sandbox client. Does not replace the cached client."""
    if not paypal_sdk_reads_enabled():
        raise RuntimeError("PayPal SDK reads are disabled")
    _require_sandbox()
    client_id = os.environ.get("PAYPAL_CLIENT_ID") or ""
    client_secret = os.environ.get("PAYPAL_CLIENT_SECRET") or ""
    if not client_id or not client_secret:
        raise RuntimeError(
            "PayPal SDK gateway needs PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET"
        )

    client_mod = importlib.import_module("paypalserversdk.paypal_serversdk_client")
    config_mod = importlib.import_module("paypalserversdk.configuration")
    auth_mod = importlib.import_module("paypalserversdk.http.auth.o_auth_2")
    errors_mod = importlib.import_module("paypalserversdk.exceptions.api_exception")
    helper_mod = importlib.import_module("paypalserversdk.api_helper")

    global _API_EXCEPTION, _API_HELPER
    _API_EXCEPTION = errors_mod.ApiException
    _API_HELPER = helper_mod.APIHelper

    sandbox = config_mod.Environment.SANDBOX
    credentials = auth_mod.ClientCredentialsAuthCredentials(
        o_auth_client_id=client_id,
        o_auth_client_secret=client_secret,
    )
    sdk = client_mod.PaypalServersdkClient(
        environment=sandbox,
        timeout=_TIMEOUT_SECONDS,
        max_retries=_MAX_RETRIES,
        client_credentials_auth_credentials=credentials,
        http_client_instance=http_client_instance,
        http_call_back=http_call_back,
    )
    if sdk.config.environment is not sandbox:
        raise RuntimeError("PayPal SDK gateway refuses a non-sandbox environment")
    if sdk.config.get_base_uri() != SANDBOX_BASE:
        raise RuntimeError("PayPal SDK gateway refuses a non-sandbox host")
    if sdk.config.timeout != _TIMEOUT_SECONDS or sdk.config.max_retries != _MAX_RETRIES:
        raise RuntimeError("PayPal SDK gateway lost its timeout or retry settings")
    return sdk


def client() -> Any:
    """Return the process-wide sandbox client, building it on first use."""
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            _CLIENT = build_sandbox_client()
        return _CLIENT


def _raise_paypal_error(status: int, body: Any) -> NoReturn:
    """Raise the existing ``PayPalError`` without a static import cycle."""
    module = importlib.import_module("app.escales.paypal_client")
    error_cls = module.PayPalError
    raise error_cls(status, body)


def _reraise_api_error(exc: BaseException) -> None:
    api_type = _API_EXCEPTION
    if api_type is None or not isinstance(exc, api_type):
        return
    response = getattr(exc, "response", None)
    text = getattr(response, "text", None) if response is not None else None
    code = getattr(exc, "response_code", None)
    status = code if isinstance(code, int) else 502
    body: Any = text if isinstance(text, str) else ""
    try:
        _raise_paypal_error(status, body)
    except Exception as mapped:
        raise mapped from exc


def _body_dict(body: Any) -> dict[str, Any]:
    if body is None:
        return {}
    helper = _API_HELPER
    raw: Any = body if isinstance(body, dict) else helper.to_dictionary(body)
    if not isinstance(raw, dict):
        _raise_paypal_error(502, "PayPal SDK response was not an object")
    return {str(key): value for key, value in raw.items()}


def _execute(controller_name: str, operation: str, *args: Any) -> dict[str, Any]:
    sdk = client()
    controller = getattr(sdk, controller_name)
    operation_fn = getattr(controller, operation)
    try:
        result = operation_fn(*args)
    except Exception as exc:
        _reraise_api_error(exc)
        raise
    return _body_dict(getattr(result, "body", None))


def get_order(order_id: str) -> dict[str, Any]:
    return _execute("orders", "get_order", {"id": order_id})


def get_authorized_payment(authorization_id: str) -> dict[str, Any]:
    return _execute(
        "payments",
        "get_authorized_payment",
        {"authorization_id": authorization_id},
    )


def get_setup_token(setup_token_id: str) -> dict[str, Any]:
    return _execute("vault", "get_setup_token", setup_token_id)


def get_billing_plan(plan_id: str) -> dict[str, Any]:
    return _execute("subscriptions", "get_billing_plan", plan_id)


def list_billing_plans(*, product_id: str, page_size: int = 20) -> dict[str, Any]:
    return _execute(
        "subscriptions",
        "list_billing_plans",
        {
            "product_id": product_id,
            "page_size": page_size,
            "total_required": True,
        },
    )


def get_subscription(subscription_id: str) -> dict[str, Any]:
    return _execute("subscriptions", "get_subscription", {"id": subscription_id})


def search_transactions(*, start_date: str, end_date: str) -> dict[str, Any]:
    return _execute(
        "transaction_search",
        "search_transactions",
        {
            "start_date": start_date,
            "end_date": end_date,
            "fields": "all",
            "page_size": 100,
        },
    )
