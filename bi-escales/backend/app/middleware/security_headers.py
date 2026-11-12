"""Security response headers on every HTTP response (including errors)."""
from __future__ import annotations

import os
from typing import Iterable

from fastapi import FastAPI

SECURITY_HEADERS_ENV = "ESCALES_SECURITY_HEADERS"

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}

HSTS_VALUE = "max-age=15552000; includeSubDomains"
X_CONTENT_TYPE_OPTIONS = "nosniff"
REFERRER_POLICY = "strict-origin-when-cross-origin"

# Enforced CSP: only frame-ancestors (PayPal popups/iframes are not restricted here).
CSP_ENFORCED = "frame-ancestors 'none'"

# Report-only full policy (sources traced from frontend PayPal SDK + NAVIGUIDE map tiles).
_PAYPAL_SCRIPT = (
    "https://www.paypal.com",
    "https://*.paypal.com",
    "https://*.paypalobjects.com",
)
# Google Pay and Apple Pay scripts loaded by the v6 wallet buttons.
_WALLET_SCRIPT = (
    "https://pay.google.com",
    "https://applepay.cdn-apple.com",
)
_PAYPAL_FRAME = (
    "https://www.paypal.com",
    "https://www.sandbox.paypal.com",
    "https://*.paypal.com",
)
_PAYPAL_CONNECT = (
    "https://api-m.sandbox.paypal.com",
    "https://www.paypal.com",
    "https://*.paypal.com",
    "https://*.paypalobjects.com",
)
_MAP_TILES = ("https://server.arcgisonline.com",)


def security_headers_enabled() -> bool:
    """Default on unless ESCALES_SECURITY_HEADERS is explicitly false."""
    raw = os.environ.get(SECURITY_HEADERS_ENV, "").strip().lower()
    if not raw:
        return True
    if raw in _FALSY:
        return False
    if raw in _TRUTHY:
        return True
    return True


def build_csp_enforced() -> str:
    return CSP_ENFORCED


def build_csp_report_only() -> str:
    """Single-line CSP for Report-Only (monitoring only; does not block)."""
    parts = [
        "default-src 'self'",
        "script-src 'self' " + " ".join(_PAYPAL_SCRIPT + _WALLET_SCRIPT),
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob: " + " ".join(_MAP_TILES + _PAYPAL_SCRIPT),
        "font-src 'self'",
        "connect-src 'self' " + " ".join(_PAYPAL_CONNECT),
        "frame-src 'self' " + " ".join(_PAYPAL_FRAME),
        "frame-ancestors 'none'",
    ]
    return "; ".join(parts)


def security_header_items() -> Iterable[tuple[bytes, bytes]]:
    yield b"strict-transport-security", HSTS_VALUE.encode("ascii")
    yield b"x-content-type-options", X_CONTENT_TYPE_OPTIONS.encode("ascii")
    yield b"referrer-policy", REFERRER_POLICY.encode("ascii")
    yield b"content-security-policy", build_csp_enforced().encode("ascii")
    yield (
        b"content-security-policy-report-only",
        build_csp_report_only().encode("ascii"),
    )


class SecurityHeadersMiddleware:
    """Pure ASGI middleware so error and static responses all get headers."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not security_headers_enabled():
            await self.app(scope, receive, send)
            return

        extra = list(security_header_items())

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(extra)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def install_security_headers(application: FastAPI) -> None:
    application.add_middleware(SecurityHeadersMiddleware)
