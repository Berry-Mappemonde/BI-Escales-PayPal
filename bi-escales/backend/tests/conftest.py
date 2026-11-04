"""Shared pytest hooks. Registers the optional PayPal sandbox marker."""

import pytest


@pytest.fixture(autouse=True)
def _reset_llm_hop_blocks():
    from app.core import llm

    llm.reset_hop_blocks()
    llm.reset_nim_pace()
    llm.reset_nim_model_choice()
    yield
    llm.reset_hop_blocks()
    llm.reset_nim_model_choice()


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: external PayPal or NIM call; skipped unless the matching credential is set",
    )
