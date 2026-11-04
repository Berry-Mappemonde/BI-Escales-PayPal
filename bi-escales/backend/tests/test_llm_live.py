"""Optional live NIM call. Skipped unless NVIDIA_API_KEY is set. No secrets stored."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import llm


@pytest.mark.live
def test_live_nim_answers(monkeypatch):
    if not os.environ.get("NVIDIA_API_KEY", "").strip():
        pytest.skip("NVIDIA_API_KEY is not set")
    monkeypatch.setenv("ESCALES_LLM_ENABLED", "1")
    monkeypatch.setenv("ESCALES_LLM_NEBIUS_ENABLED", "false")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)

    async def body():
        try:
            return await asyncio.wait_for(
                llm.ask_text(
                    "Reply with exactly the word ready.",
                    system="You reply with one word.",
                    max_tokens=32,
                    temperature=0.2,
                ),
                timeout=45,
            )
        except Exception:
            return None

    result = asyncio.run(body())
    if result is None or not str(getattr(result, "text", "") or "").strip():
        pytest.skip("NIM did not answer")
    assert result.provider == "nim"
    assert result.model
