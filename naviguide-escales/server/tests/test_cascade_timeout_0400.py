"""Offline regression coverage for the judges' LLM cascade timeout contract."""

import asyncio

import httpx
import pytest

import story_cascade


@pytest.fixture(autouse=True)
def _clean_cascade_env(monkeypatch):
    monkeypatch.delenv("NAVIGUIDE_LLM_PROVIDERS", raising=False)
    monkeypatch.delenv("NAVIGUIDE_LLM_TIMEOUT_FALLBACK", raising=False)
    monkeypatch.setenv("NAVIGUIDE_LLM_CACHE_TTL_S", "0")
    monkeypatch.setenv("NAVIGUIDE_TF_MODEL_GUARD", "0")
    # The cascade skips the Token Factory hop when no key is configured (RL185).
    # These tests mock _call_tokenfactory, so pretend a key exists to exercise
    # the TF failure -> fallback path offline; no real call is ever made.
    monkeypatch.setattr(story_cascade, "nebius_key", lambda: "offline-test")
    story_cascade.reset_runtime()
    yield
    story_cascade.reset_runtime()


@pytest.mark.parametrize(
    "failure",
    ["httpx", "asyncio", "402", "429", "5xx"],
)
@pytest.mark.parametrize("path", ["story", "chat", "film-writing"])
def test_tf_failure_keeps_cascade_available_for_each_writing_path(monkeypatch, failure, path):
    """Exercise the shared cascade at the tier used by each production path."""
    calls = []

    async def tf(*_args, **_kwargs):
        calls.append("tokenfactory")
        if failure == "httpx":
            raise httpx.ReadTimeout("mock TF timeout")
        if failure == "asyncio":
            raise asyncio.TimeoutError("mock TF timeout")
        status = {"402": 402, "429": 429, "5xx": 503}.get(failure)
        raise RuntimeError(f"Token Factory HTTP {status}")

    async def nim(*_args, **_kwargs):
        calls.append("nim")
        return "NIM: texte de secours", "nvidia-openai/gpt-oss-20b"

    async def later(*_args, **_kwargs):
        pytest.fail("La cascade doit s'arrêter au premier fournisseur disponible")

    monkeypatch.setattr(story_cascade, "_call_tokenfactory", tf)
    monkeypatch.setattr(story_cascade, "_call_nim", nim)
    monkeypatch.setattr(story_cascade, "_call_openrouter", later)
    monkeypatch.setattr(story_cascade, "_call_claude", later)

    tier = {"story": "write", "chat": "judge", "film-writing": "write"}[path]

    async def run():
        return await story_cascade.cascade_text(
            f"{path} system", f"{path} user", tier=tier,
            fallback="Texte des règles.", facts=None,
        )

    text, source = asyncio.run(run())
    assert calls == ["tokenfactory", "nim"]
    assert text
    assert source.startswith("nvidia-")


def test_timeout_fallback_is_enabled_by_default(monkeypatch):
    monkeypatch.delenv("NAVIGUIDE_LLM_TIMEOUT_FALLBACK", raising=False)
    assert story_cascade.timeout_fallback_allowed() is True


@pytest.mark.parametrize("failure", ["httpx", "asyncio", "402", "429", "5xx"])
def test_all_provider_failures_return_nonempty_rules_fallback(monkeypatch, failure):
    calls = []

    async def down(name):
        calls.append(name)
        if name == "tokenfactory" and failure == "httpx":
            raise httpx.ReadTimeout("mock TF timeout")
        if name == "tokenfactory" and failure == "asyncio":
            raise asyncio.TimeoutError("mock TF timeout")
        if name == "tokenfactory" and failure in {"402", "429", "5xx"}:
            raise RuntimeError(f"Token Factory HTTP {failure}")
        if name == "nim":
            raise httpx.ReadTimeout("mock NIM timeout")
        raise RuntimeError(f"{name} unavailable")

    async def tf(*_args, **_kwargs):
        return await down("tokenfactory")

    async def nim(*_args, **_kwargs):
        return await down("nim")

    async def openrouter(*_args, **_kwargs):
        return await down("openrouter")

    async def claude(*_args, **_kwargs):
        return await down("claude")

    monkeypatch.setattr(story_cascade, "_call_tokenfactory", tf)
    monkeypatch.setattr(story_cascade, "_call_nim", nim)
    monkeypatch.setattr(story_cascade, "_call_openrouter", openrouter)
    monkeypatch.setattr(story_cascade, "_call_claude", claude)

    async def run():
        return await story_cascade.cascade_text(
            "system", "user", tier="write", fallback="Phrase locale issue des règles.", facts=None,
        )

    text, source = asyncio.run(run())
    assert calls == ["tokenfactory", "nim", "openrouter", "claude"]
    assert source == "rules"
    assert text == "Phrase locale issue des règles."
    assert text.strip()
