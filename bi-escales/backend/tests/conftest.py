"""Shared pytest hooks. Registers the optional PayPal sandbox marker."""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: PayPal sandbox call; skipped unless PAYPAL_CLIENT_ID is set",
    )
