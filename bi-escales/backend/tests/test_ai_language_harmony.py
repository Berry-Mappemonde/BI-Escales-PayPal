"""Each AI call type uses prompts and outputs in the app-selected language."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import llm
from app.escales.captain import chat, review
from app.escales.milestones import record_evidence
from app.escales.pledges import reset_ledger

SUPER = "I'd like to sponsor 120 nautical miles near Ajaccio"
FRENCH = "Je voudrais parrainer 120 milles près d'Ajaccio"


def _french_only(reply: str) -> None:
    folded = reply.casefold()
    for word in ("stopover", "leg", "intent", "sponsored miles"):
        assert word not in folded, reply


def _english_only(reply: str) -> None:
    folded = reply.casefold()
    for word in ("escale", "milles", "parrain", "trésorier", "étape", "quelle"):
        assert word not in folded, reply


@pytest.mark.parametrize(
    "app_lang,system_needle,reply_text,check_reply",
    [
        ("en", "Reply in English only", "The sea is calm.", _english_only),
        ("fr", "uniquement en français", "La mer est calme.", _french_only),
    ],
)
def test_chat_llm_prompt_and_reply_match_app_lang(
    monkeypatch, app_lang, system_needle, reply_text, check_reply,
):
    captured: list[str] = []

    async def fake_ask(*_args, system=None, **_kwargs):
        captured.append(system or "")
        return llm.LlmResult(reply_text, "nim", llm.NIM_MODEL_DEFAULT)

    monkeypatch.setattr(llm, "has_llm", lambda: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask)

    async def body():
        result = await chat(SUPER if app_lang == "en" else FRENCH, lang=app_lang)
        assert captured, "expected one LLM call"
        assert system_needle.casefold() in captured[0].casefold()
        check_reply(result["reply"])

    asyncio.run(body())


@pytest.mark.parametrize(
    "app_lang,report_needle,json_needle,narrative,reason",
    [
        (
            "en",
            "Write in English only",
            "Write reason in English",
            "The boat is heading toward Lorient.",
            "Evidence pending.",
        ),
        (
            "fr",
            "uniquement en français",
            "reason en français",
            "Le bateau se dirige vers Lorient.",
            "Preuve en attente.",
        ),
    ],
)
def test_review_report_and_advisory_match_app_lang(
    monkeypatch, app_lang, report_needle, json_needle, narrative, reason,
):
    text_calls: list[str] = []
    json_calls: list[dict] = []

    async def fake_text(*_args, system=None, **_kwargs):
        text_calls.append(system or "")
        return llm.LlmResult(narrative, "nim", llm.NIM_MODEL_DEFAULT)

    async def fake_json(*_args, system=None, schema=None, **_kwargs):
        json_calls.append({"system": system or "", "schema": schema or {}})
        return llm.LlmJson(
            {"proposal": "wait", "reason": reason},
            "nim_fallback",
            llm.NIM_FALLBACK_MODEL_DEFAULT,
            f'{{"proposal":"wait","reason":{reason!r}}}',
        )

    monkeypatch.setattr(llm, "has_llm", lambda: True)
    monkeypatch.setattr(llm, "ask_text", fake_text)
    monkeypatch.setattr(llm, "ask_json", fake_json)
    reset_ledger()

    async def body():
        await record_evidence("lorient", met=False, facts={"port": "Lorient"})
        result = await review("lorient", reader=None, lang=app_lang)
        assert text_calls, "expected report LLM call"
        assert report_needle.casefold() in text_calls[0].casefold()
        assert json_calls, "expected advisory ask_json"
        assert json_needle.casefold() in json_calls[0]["system"].casefold()
        schema = json_calls[0]["schema"]
        props = schema.get("properties") or {}
        reason_desc = (props.get("reason") or {}).get("description") or ""
        if app_lang == "fr":
            assert "français" in reason_desc.casefold()
            assert "fr" in result.get("report", "").casefold() or "lorient" in result.get("report", "").casefold()
        else:
            assert "english" in reason_desc.casefold()
        advisory = result.get("llm_proposal") or {}
        assert advisory.get("reason") == reason

    asyncio.run(body())
    reset_ledger()
