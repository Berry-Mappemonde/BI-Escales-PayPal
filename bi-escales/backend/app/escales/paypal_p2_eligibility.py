"""P2 PayPal product eligibility for Berry-Mappemonde (EUR, France-facing, sandbox).

Sources: PayPal Developer docs (Pay Later overview, Subscriptions, Invoicing,
Customer Disputes, Venmo, Fastlane) — verified read-only for sandbox planning.
"""

from __future__ import annotations

# Pay Later — France Pay in 4 (developer.paypal.com/docs/checkout/pay-later/)
PAY_LATER_FR_MIN_EUR = "20.00"
PAY_LATER_FR_MAX_EUR = "3000.00"
PAY_LATER_FR_PRODUCT = "Pay in 4 (4 monthly payments)"

# Escales UI uses a conservative floor for messaging placement (≥30 EUR pledges).
PAY_LATER_UI_MIN_EUR = "30.00"

# Venmo — US buyers, USD merchants only (disable-funding=venmo in our SDK).
VENMO_ELIGIBLE_ESCales = False

# Fastlane — guest checkout acceleration; official availability is US-centric today.
FASTLANE_ELIGIBLE_EUR_FR = False

# Subscriptions — Billing API supports EUR in EU sandbox/live when the merchant account is enabled.
SUBSCRIPTIONS_EUR_FR_SANDBOX = True

# Invoicing v2 — EUR invoices for FR merchants in sandbox when invoicing is enabled on the app.
INVOICING_EUR_FR_SANDBOX = True

# Customer Disputes v1 — available for card/PayPal commerce in supported regions including FR/EUR.
DISPUTES_EUR_FR_SANDBOX = True


def p2_eligibility_report() -> dict:
    """Structured notes for API / PR (no secrets)."""
    return {
        "merchant": {"currency": "EUR", "country": "FR", "environment": "sandbox"},
        "pay_later": {
            "eligible": True,
            "product": PAY_LATER_FR_PRODUCT,
            "min_eur": PAY_LATER_FR_MIN_EUR,
            "max_eur": PAY_LATER_FR_MAX_EUR,
            "ui_messaging_min_eur": PAY_LATER_UI_MIN_EUR,
            "requirements": [
                "France-based PayPal merchant",
                "France-facing website",
                "EUR one-time checkout integration",
            ],
        },
        "venmo": {
            "eligible": VENMO_ELIGIBLE_ESCales,
            "reason": "Venmo is US-only (USD); Escales checkout is EUR.",
        },
        "fastlane": {
            "eligible": FASTLANE_ELIGIBLE_EUR_FR,
            "reason": "Not implemented: Fastlane is not documented for EUR/FR merchant checkout in our integration scope.",
        },
        "subscriptions": {
            "eligible": SUBSCRIPTIONS_EUR_FR_SANDBOX,
            "currency": "EUR",
            "note": "Requires Billing plan + product; sandbox app must include subscription scopes.",
        },
        "invoicing": {
            "eligible": INVOICING_EUR_FR_SANDBOX,
            "currency": "EUR",
        },
        "disputes": {
            "eligible": DISPUTES_EUR_FR_SANDBOX,
            "api": "Customer Disputes v1",
        },
    }
