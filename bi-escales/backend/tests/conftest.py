"""Shared pytest hooks. Registers the optional PayPal sandbox marker."""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: external PayPal or NIM call; skipped unless the matching credential is set",
    )
