"""Minimal LLM seam for the standalone repo.

In Blue-Intelligence this module is the LLM cascade. Here no model is
configured by default, so the AI Captain uses its deterministic fallback.
Plug a provider in by implementing has_llm() and ask_text().
"""
from typing import Optional


def has_llm() -> bool:
    return False


async def ask_text(prompt: str, system: Optional[str] = None, max_tokens: int = 500) -> str:
    raise RuntimeError("No LLM configured")
