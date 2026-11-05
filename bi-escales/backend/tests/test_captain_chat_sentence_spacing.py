"""Captain chat reply: no glued sentence stops before a capital letter."""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.core.llm as llm
from app.escales.captain import chat
from app.escales.pledges import reset_ledger

# Uppercase letter after . ! ? without an intervening space (decimals use a digit next).
_GLUE_AFTER_STOP = re.compile(r"(?<![0-9])[.!?…](?=[A-ZÀ-ÿ])")


def _assert_no_sentence_glue(text: str) -> None:
    match = _GLUE_AFTER_STOP.search(text or "")
    assert match is None, f"glued stop before capital: {match.group(0)!r} in {text!r}"


def test_chat_assembly_fr_and_en_no_glued_stops(monkeypatch):
    async def run() -> None:
        reset_ledger()
        monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)

        async def fr_model(*_args, **_kwargs):
            return "Pour cette étape.La promesse est autorisée au plus près du départ."

        monkeypatch.setattr(llm, "ask_text", fr_model)
        fr = await chat("250 mi près de Dakar", lang="fr")
        reply_fr = str(fr.get("reply") or "")
        _assert_no_sentence_glue(reply_fr)
        assert ". La promesse" in reply_fr
        assert "étape. Au-delà" in reply_fr or ". Au-delà" in reply_fr

        reset_ledger()

        async def en_model(*_args, **_kwargs):
            return "For this leg.A pledge is authorized as close to departure as possible."

        monkeypatch.setattr(llm, "ask_text", en_model)
        en = await chat("250 mi near Dakar", lang="en")
        reply_en = str(en.get("reply") or "")
        _assert_no_sentence_glue(reply_en)
        assert ". A pledge" in reply_en
        assert "leg. When" in reply_en

    asyncio.run(run())


def test_finish_text_keeps_lowercase_after_dot_in_urls():
    from app.escales.captain import _finish_text

    text = "Membership: https://www.example.com/associations/foo."
    finished = _finish_text(text)
    assert "example.com" in finished
    _assert_no_sentence_glue(finished)
