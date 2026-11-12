"""PayPal Server SDK gateway. Sandbox only.

The process keeps one ``PaypalServersdkClient``. ``paypalserversdk`` is imported
inside :func:`build_sandbox_client`, and only when ``ESCALES_PAYPAL_SDK_ENABLED``
is truthy and ``PAYPAL_ENV`` is ``sandbox``.

Reads and writes share that flag. ``PayPalClient`` calls
:func:`paypal_sdk_reads_enabled` before either path. A false result keeps the
httpx client. Build refusal logs one warning and does not raise. Connection
errors and timeouts become ``PayPalError`` with status 502.

Write bodies are generated models. The HTTP path and the ``PayPal-Request-Id``
stay the values ``PayPalClient`` already used. See ``paypal-plan.md``.
"""

from __future__ import annotations

import datetime as dt
import importlib
import logging
from collections.abc import Callable, MutableMapping
import math
import os
import random
import threading
import time
from contextvars import ContextVar
from email.utils import parsedate_to_datetime
from typing import Any, NoReturn

from .config import SANDBOX_BASE, paypal_sdk_reads_enabled as _flag_enabled

log = logging.getLogger("escales.paypal.sdk")

_FALLBACK_LOG = "PayPal SDK read gateway unavailable; using the httpx client"
_TRANSPORT_BODY = "PayPal SDK transport failure"
_TRANSPORT_TYPES = frozenset({
    ("requests.exceptions", "ConnectionError"),
    ("requests.exceptions", "Timeout"),
    ("urllib3.exceptions", "MaxRetryError"),
    ("urllib3.exceptions", "NewConnectionError"),
    ("urllib3.exceptions", "ProtocolError"),
    ("urllib3.exceptions", "TimeoutError"),
    ("builtins", "ConnectionError"),
    ("builtins", "TimeoutError"),
})

_TIMEOUT_SECONDS = 30
_MAX_RETRIES = 0
_RESOURCE_ATTEMPTS = 3
_CALL_BUDGET: ContextVar[Any] = ContextVar("paypal_call_budget", default=None)
_PASSTHROUGH: ContextVar[dict[str, str] | None] = ContextVar(
    "paypal_sdk_passthrough_headers", default=None,
)

_CLIENT: Any = None
_CLIENT_LOCK = threading.Lock()
_API_EXCEPTION: Any = None
_API_HELPER: Any = None
_FALLBACK_REASONS: set[str] = set()
_UNSET: Any = object()
_PREFER_REPRESENTATION = "return=representation"


def reset_client() -> None:
    """Drop the cached client and the one-shot fallback log.

    Tests use this between cases.
    """
    global _CLIENT
    with _CLIENT_LOCK:
        _CLIENT = None
        _FALLBACK_REASONS.clear()


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


class _PassthroughHeaders:
    """Add headers the generated method cannot set, then call the test catcher.

    SDK 2.4.0 omits PayPal-Mock-Response on reauthorize and setup-token creation,
    and delete_payment_token accepts only the token id. The context var is empty
    for every other call, so those requests are unchanged. OAuth is left alone.
    """

    def __init__(self, inner: Any = None) -> None:
        self._inner = inner

    def on_before_request(self, request: Any) -> None:
        extra = _PASSTHROUGH.get()
        url = str(getattr(request, "query_url", "") or "")
        headers = getattr(request, "headers", None)
        if extra and isinstance(headers, MutableMapping) and "/v1/oauth2/token" not in url:
            present = {str(key).lower() for key in headers}
            for key, value in extra.items():
                if value and key.lower() not in present:
                    request.add_header(key, value)
        if self._inner is not None:
            self._inner.on_before_request(request)

    def on_after_response(self, http_response: Any) -> None:
        if self._inner is not None:
            self._inner.on_after_response(http_response)


def _with_passthrough(
    run: Callable[[], dict[str, Any]],
    *,
    mock_response: str | None = None,
    request_id: str | None = None,
    prefer: bool = False,
) -> dict[str, Any]:
    headers: dict[str, str] = {}
    mock = (mock_response or "").strip()
    if mock:
        headers["PayPal-Mock-Response"] = mock
    if request_id:
        headers["PayPal-Request-Id"] = _request_id(request_id)
    if prefer:
        headers["Prefer"] = _PREFER_REPRESENTATION
    token = _PASSTHROUGH.set(headers or None)
    try:
        return run()
    finally:
        _PASSTHROUGH.reset(token)


def build_sandbox_client(
    *,
    http_client_instance: Any = None,
    http_call_back: Any = None,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> Any:
    """Build a sandbox client. Does not replace the cached client."""
    if not _flag_enabled():
        raise RuntimeError("PayPal SDK reads are disabled")
    _require_sandbox()
    if client_id is None and client_secret is None:
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
        http_call_back=_PassthroughHeaders(http_call_back),
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


def paypal_sdk_reads_enabled() -> bool:
    """Selector for ``PayPalClient._sdk_reads``.

    False keeps the httpx path. ``_sdk_reads`` lives in ``paypal_client`` and
    is not modified here: a false result is how a refused build falls back.
    Each distinct reason is logged once per process.
    """
    reason = _httpx_fallback_reason()
    if reason is None:
        return True
    _log_fallback_once(reason)
    return False


def _env_is_sandbox() -> bool:
    return (os.environ.get("PAYPAL_ENV") or "").strip().lower() == "sandbox"


def _httpx_fallback_reason() -> str | None:
    if not _flag_enabled():
        return "ESCALES_PAYPAL_SDK_ENABLED is off"
    if not _env_is_sandbox():
        return "PAYPAL_ENV is not sandbox"
    try:
        client()
    except (RuntimeError, ModuleNotFoundError, AttributeError, TypeError) as exc:
        # Constructor exceptions can contain request configuration. Never log it.
        return f"SDK client build failed: {type(exc).__name__}"
    return None


def _log_fallback_once(reason: str) -> None:
    with _CLIENT_LOCK:
        if reason in _FALLBACK_REASONS:
            return
        _FALLBACK_REASONS.add(reason)
    log.warning("%s (%s)", _FALLBACK_LOG, reason)


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
    if body is None or body == "" or body == b"":
        return {}
    helper = _API_HELPER
    raw: Any = body if isinstance(body, dict) else helper.to_dictionary(body)
    if not isinstance(raw, dict):
        _raise_paypal_error(502, "PayPal SDK response was not an object")
    return {str(key): value for key, value in raw.items()}


def _type_is_transport(cls: type[BaseException]) -> bool:
    for base in cls.mro():
        if (base.__module__, base.__name__) in _TRANSPORT_TYPES:
            return True
    return False


def _is_transport_error(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if _type_is_transport(type(current)):
            return True
        cause = current.__cause__
        current = cause if isinstance(cause, BaseException) else None
    return False


def _reraise_transport_error(exc: BaseException) -> None:
    if not _is_transport_error(exc):
        return
    try:
        _raise_paypal_error(502, f"{_TRANSPORT_BODY}: {type(exc).__name__}")
    except Exception as mapped:
        raise mapped from exc


def _retry_delay(exc: Exception, attempt: int) -> float | None:
    if _API_EXCEPTION is None or not isinstance(exc, _API_EXCEPTION):
        return None
    code = getattr(exc, "response_code", None)
    if code != 429 and not (isinstance(code, int) and 500 <= code <= 599):
        return None
    headers = getattr(getattr(exc, "response", None), "headers", {}) or {}
    raw = next((str(value) for key, value in headers.items() if str(key).lower() == "retry-after"), "0")
    try:
        retry_after = max(0.0, float(raw))
    except ValueError:
        try:
            target = parsedate_to_datetime(raw)
            if target.tzinfo is None:
                target = target.replace(tzinfo=dt.timezone.utc)
            retry_after = max(0.0, (target - dt.datetime.now(dt.timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            retry_after = 0.0
    if not math.isfinite(retry_after) or retry_after > 10.0:
        return None
    return float(min(10.0, max(0.25 * (2 ** attempt), retry_after) + random.uniform(0, 0.25)))


def _execute(controller_name: str, operation: str, *args: Any, sdk: Any = None) -> dict[str, Any]:
    sdk = sdk if sdk is not None else client()
    controller = getattr(sdk, controller_name)
    operation_fn = getattr(controller, operation)
    last_error: Exception | None = None
    for attempt in range(_RESOURCE_ATTEMPTS):
        budget = _CALL_BUDGET.get()
        if budget is not None:
            try:
                budget.consume()
            except Exception as budget_error:
                if last_error is not None:
                    log.warning(
                        "Captain PayPal budget exhausted after HTTP %s",
                        getattr(last_error, "response_code", "unknown"),
                    )
                    raise budget_error from last_error
                raise
        try:
            result = operation_fn(*args)
        except Exception as exc:
            last_error = exc
            delay = _retry_delay(exc, attempt)
            if delay is not None and attempt < _RESOURCE_ATTEMPTS - 1:
                time.sleep(delay)
                continue
            auth_errors = importlib.import_module("apimatic_core.exceptions.auth_validation_exception")
            if isinstance(exc, auth_errors.AuthValidationException):
                try:
                    _raise_paypal_error(502, "PayPal SDK authentication unavailable")
                except Exception as mapped:
                    raise mapped from None
            _reraise_api_error(exc)
            _reraise_transport_error(exc)
            raise
        return _body_dict(getattr(result, "body", None))
    raise AssertionError("unreachable")


def _sdk_reads(captain_budget: Any, method: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Apply the caller's budget to every SDK resource attempt, including writes.

    Context-local scope prevents concurrent callers from sharing their budgets.
    OAuth remains internal to the SDK and is not charged.
    """
    if method.startswith("_"):
        _raise_paypal_error(502, "PayPal SDK response was not an object")
    operation = globals().get(method)
    if not callable(operation):
        _raise_paypal_error(502, "PayPal SDK response was not an object")
    token = _CALL_BUDGET.set(captain_budget)
    try:
        result = operation(*args, **kwargs)
    finally:
        _CALL_BUDGET.reset(token)
    if not isinstance(result, dict):
        _raise_paypal_error(502, "PayPal SDK response was not an object")
    return {str(key): value for key, value in result.items()}


def get_order(order_id: str, *, fields: str | None = None) -> dict[str, Any]:
    options = {"id": order_id}
    if fields is not None:
        options["fields"] = fields
    return _execute("orders", "get_order", options)


def get_authorized_payment(authorization_id: str) -> dict[str, Any]:
    return _execute(
        "payments",
        "get_authorized_payment",
        {"authorization_id": authorization_id},
    )


def get_captured_payment(capture_id: str) -> dict[str, Any]:
    return _execute("payments", "get_captured_payment", {"capture_id": capture_id})


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


def _model(module: str, name: str) -> Any:
    loaded = importlib.import_module(f"paypalserversdk.models.{module}")
    return getattr(loaded, name)


def _skip() -> Any:
    helper = importlib.import_module("paypalserversdk.api_helper")
    return helper.APIHelper.SKIP


def _request_id(idempotency_key: str) -> str:
    text = str(idempotency_key or "").strip()
    if not text:
        raise RuntimeError("PayPal SDK write requires a PayPal-Request-Id")
    return text[:127]


def _write_options(
    *,
    idempotency_key: str,
    mock_response: str | None = None,
    body: Any = _UNSET,
    prefer: bool = True,
    **path: Any,
) -> dict[str, Any]:
    options: dict[str, Any] = {key: value for key, value in path.items() if value is not None}
    options["paypal_request_id"] = _request_id(idempotency_key)
    if prefer:
        options["prefer"] = _PREFER_REPRESENTATION
    mock = (mock_response or "").strip()
    if mock:
        options["paypal_mock_response"] = mock
    if body is not _UNSET:
        options["body"] = body
    return options


def create_order(
    payload: dict[str, Any],
    *,
    idempotency_key: str,
    mock_response: str | None = None,
) -> dict[str, Any]:
    """Create AUTHORIZE/CAPTURE orders with generated request models."""
    # Nested dictionaries deliberately retain card experience fields that 2.4.0's
    # narrower generated submodels drop, and avoid injected checkout defaults.
    try:
        body = _model("order_request", "OrderRequest")(**payload)
    except TypeError:
        _raise_paypal_error(502, "PayPal SDK order payload is unsupported")
    return _execute(
        "orders", "create_order",
        _write_options(body=body, idempotency_key=idempotency_key,
                       mock_response=mock_response),
    )


def authorize_order(
    order_id: str,
    *,
    idempotency_key: str,
    mock_response: str | None = None,
) -> dict[str, Any]:
    body = _model("order_authorize_request", "OrderAuthorizeRequest")()
    return _execute(
        "orders",
        "authorize_order",
        _write_options(
            id=order_id,
            idempotency_key=idempotency_key,
            mock_response=mock_response,
            body=body,
        ),
    )


def capture_order(
    order_id: str,
    *,
    idempotency_key: str,
    mock_response: str | None = None,
) -> dict[str, Any]:
    body = _model("order_capture_request", "OrderCaptureRequest")()
    return _execute(
        "orders",
        "capture_order",
        _write_options(
            id=order_id,
            idempotency_key=idempotency_key,
            mock_response=mock_response,
            body=body,
        ),
    )


def capture_authorized_payment(
    authorization_id: str,
    *,
    final_capture: bool,
    idempotency_key: str,
    mock_response: str | None = None,
) -> dict[str, Any]:
    body = _model("capture_request", "CaptureRequest")(final_capture=bool(final_capture))
    return _execute(
        "payments",
        "capture_authorized_payment",
        _write_options(
            authorization_id=authorization_id,
            idempotency_key=idempotency_key,
            mock_response=mock_response,
            body=body,
        ),
    )


def void_payment(
    authorization_id: str,
    *,
    idempotency_key: str,
    mock_response: str | None = None,
) -> dict[str, Any]:
    return _execute(
        "payments",
        "void_payment",
        _write_options(
            authorization_id=authorization_id,
            idempotency_key=idempotency_key,
            mock_response=mock_response,
        ),
    )


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return {}


def _vault_experience(context: dict[str, Any]) -> Any:
    experience = _model("vault_experience_context", "VaultExperienceContext")
    skip = _skip()
    return experience(
        brand_name=context.get("brand_name") or skip,
        locale=context.get("locale") or skip,
        return_url=context.get("return_url") or skip,
        cancel_url=context.get("cancel_url") or skip,
        shipping_preference=context.get("shipping_preference") or "NO_SHIPPING",
        user_action=context.get("user_action") or "CONTINUE",
    )


def create_setup_token(
    body: dict[str, Any],
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    """Map the httpx setup-token JSON onto ``SetupTokenRequest``."""
    customer = _as_dict(body.get("customer"))
    source = _as_dict(body.get("payment_source"))
    paypal = _as_dict(source.get("paypal"))
    context = _as_dict(paypal.get("experience_context"))
    skip = _skip()
    wallet = _model("vault_paypal_wallet_request", "VaultPaypalWalletRequest")(
        usage_pattern=paypal.get("usage_pattern") or skip,
        usage_type=paypal.get("usage_type") or skip,
        permit_multiple_payment_tokens=bool(paypal.get("permit_multiple_payment_tokens")),
        experience_context=_vault_experience(context),
    )
    payment_source = _model(
        "setup_token_request_payment_source",
        "SetupTokenRequestPaymentSource",
    )(paypal=wallet)
    request = _model("setup_token_request", "SetupTokenRequest")(
        payment_source=payment_source,
        customer=_model("customer", "Customer")(id=str(customer.get("id") or "")),
    )
    return _execute(
        "vault",
        "create_setup_token",
        _write_options(idempotency_key=idempotency_key, body=request, prefer=False),
    )


def create_payment_token(
    body: dict[str, Any],
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    """Map the httpx payment-token JSON onto ``PaymentTokenRequest``."""
    source = _as_dict(body.get("payment_source"))
    token = _as_dict(source.get("token"))
    vault_token = _model("vault_token_request", "VaultTokenRequest")(
        id=token.get("id"),
        mtype=token.get("type"),
    )
    payment_source = _model(
        "payment_token_request_payment_source",
        "PaymentTokenRequestPaymentSource",
    )(token=vault_token)
    request = _model("payment_token_request", "PaymentTokenRequest")(payment_source=payment_source)
    return _execute(
        "vault",
        "create_payment_token",
        _write_options(idempotency_key=idempotency_key, body=request, prefer=False),
    )


def refund_captured_payment(
    capture_id: str,
    *,
    idempotency_key: str,
    amount: dict[str, Any] | None = None,
    mock_response: str | None = None,
) -> dict[str, Any]:
    refund = _model("refund_request", "RefundRequest")
    body: Any = _UNSET
    if isinstance(amount, dict) and amount.get("value") and amount.get("currency_code"):
        money = _model("money", "Money")(
            currency_code=str(amount["currency_code"]),
            value=str(amount["value"]),
        )
        body = refund(amount=money)
    return _execute(
        "payments",
        "refund_captured_payment",
        _write_options(
            capture_id=capture_id,
            idempotency_key=idempotency_key,
            mock_response=mock_response,
            body=body,
        ),
    )


def create_subscription(
    body: dict[str, Any],
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    """Map the httpx subscription JSON. Omit deprecated ``auto_renewal``."""
    context_body = _as_dict(body.get("application_context"))
    skip = _skip()
    context = _model("subscription_application_context", "SubscriptionApplicationContext")(
        return_url=context_body.get("return_url"),
        cancel_url=context_body.get("cancel_url"),
        brand_name=context_body.get("brand_name") or skip,
        locale=context_body.get("locale") or skip,
        shipping_preference=context_body.get("shipping_preference") or "NO_SHIPPING",
        user_action=context_body.get("user_action") or "SUBSCRIBE_NOW",
    )
    request = _model("create_subscription_request", "CreateSubscriptionRequest")(
        plan_id=body.get("plan_id"),
        application_context=context,
    )
    if hasattr(request, "auto_renewal"):
        del request.auto_renewal
    return _execute(
        "subscriptions",
        "create_subscription",
        _write_options(idempotency_key=idempotency_key, body=request, prefer=True),
    )


def create_billing_plan(payload: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
    body = _model("plan_request", "PlanRequest")(**payload)
    return _execute("subscriptions", "create_billing_plan",
                    _write_options(body=body, idempotency_key=idempotency_key))


def reauthorize_payment(
    authorization_id: str,
    *,
    idempotency_key: str,
    mock_response: str | None = None,
) -> dict[str, Any]:
    """POST reauthorize. SDK 2.4.0 has no mock header on this operation."""
    body = _model("reauthorize_request", "ReauthorizeRequest")()

    def run() -> dict[str, Any]:
        return _execute(
            "payments",
            "reauthorize_payment",
            _write_options(
                authorization_id=authorization_id,
                idempotency_key=idempotency_key,
                mock_response=mock_response,
                body=body,
            ),
        )

    return _with_passthrough(run, mock_response=mock_response)


def create_card_setup_token(
    body: dict[str, Any],
    *,
    idempotency_key: str,
    mock_response: str | None = None,
) -> dict[str, Any]:
    """POST the card setup-token JSON unchanged.

    ``SetupTokenRequestCard`` drops usage_type, usage_pattern,
    permit_multiple_payment_tokens and attributes.verification.
    """

    def run() -> dict[str, Any]:
        return _execute(
            "vault",
            "create_setup_token",
            _write_options(
                idempotency_key=idempotency_key,
                body=body,
                prefer=False,
                mock_response=mock_response,
            ),
        )

    return _with_passthrough(run, mock_response=mock_response, prefer=True)


def delete_payment_token(
    vault_id: str,
    *,
    idempotency_key: str,
    mock_response: str | None = None,
) -> dict[str, Any]:
    """DELETE a vault payment token. SDK 2.4.0 accepts only the id."""

    def run() -> dict[str, Any]:
        return _execute("vault", "delete_payment_token", vault_id)

    return _with_passthrough(
        run, mock_response=mock_response, request_id=idempotency_key,
    )
