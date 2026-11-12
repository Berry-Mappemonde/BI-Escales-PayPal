"""Shared pytest hooks. Registers the optional PayPal sandbox marker."""

from __future__ import annotations

import os

import httpx
import pytest

_LLM_HOSTS = (
    "integrate.api.nvidia.com",
    "openrouter.ai",
    "api.anthropic.com",
    "api.tokenfactory.nebius.com",
)

_LLM_ENV_KEYS = (
    "ESCALES_LLM_ENABLED",
    "ESCALES_LLM_NEBIUS_ENABLED",
    "NVIDIA_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENROUTER_MODEL",
    "ANTHROPIC_API_KEY",
    "NEBIUS_API_KEY",
    "NIM_MODEL",
    "NIM_FALLBACK_MODEL",
)


@pytest.fixture(autouse=True)
def _default_paypal_sandbox(monkeypatch):
    """Payment tests explicitly select sandbox; individual guard tests may override it."""
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")


@pytest.fixture(autouse=True)
def _default_escales_simulated_clock(monkeypatch):
    """Pin the voyage clock unless a test sets ESCALES_CLOCK_NOW or clears it."""
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-19T08:00:00Z")


@pytest.fixture(autouse=True)
def _reset_llm_hop_blocks():
    from app.core import llm

    llm.reset_hop_blocks()
    llm.reset_nim_pace()
    llm.reset_nim_model_choice()
    yield
    llm.reset_hop_blocks()
    llm.reset_nim_model_choice()


@pytest.fixture(autouse=True)
def _clear_leaked_llm_credentials(monkeypatch):
    """Drop real CI credentials unless a live run is requested."""
    if os.environ.get("ESCALES_RUN_LIVE", "").strip() == "1":
        yield
        return
    for name in _LLM_ENV_KEYS:
        monkeypatch.delenv(name, raising=False)
    yield


@pytest.fixture(autouse=True)
def _block_live_llm_http(monkeypatch):
    """Fail fast if a test opens a real HTTP client toward an LLM provider (CI guard)."""
    if os.environ.get("ESCALES_RUN_LIVE", "").strip() == "1":
        yield
        return

    real_client = httpx.AsyncClient

    class GuardedAsyncClient(real_client):
        def __init__(self, *args, **kwargs):
            self._escales_guard_transport = kwargs.get("transport")
            super().__init__(*args, **kwargs)

        async def post(self, url, *args, **kwargs):
            if self._escales_guard_transport is None:
                host = getattr(url, "host", None) or str(url)
                if any(marker in str(host) for marker in _LLM_HOSTS):
                    pytest.fail(
                        f"Live LLM HTTP blocked (set ESCALES_RUN_LIVE=1 to opt in): POST {url}"
                    )
            return await super().post(url, *args, **kwargs)

        async def get(self, url, *args, **kwargs):
            if self._escales_guard_transport is None:
                host = getattr(url, "host", None) or str(url)
                if any(marker in str(host) for marker in _LLM_HOSTS):
                    pytest.fail(
                        f"Live LLM HTTP blocked (set ESCALES_RUN_LIVE=1 to opt in): GET {url}"
                    )
            return await super().get(url, *args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", GuardedAsyncClient)
    yield


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: external PayPal or NIM call; skipped unless ESCALES_RUN_LIVE=1 is set",
    )


def pytest_collection_modifyitems(config, items):
    if os.environ.get("ESCALES_RUN_LIVE", "").strip() == "1":
        return
    skip_live = pytest.mark.skip(
        reason="live tests need ESCALES_RUN_LIVE=1 (see tests/README.md)",
    )
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
