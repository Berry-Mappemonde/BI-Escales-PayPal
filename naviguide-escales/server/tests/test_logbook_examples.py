"""Questions d'exemple du carnet (LogbookChat.jsx) : chacune suit le palier annoncé.

Le texte vient de src/i18n/en.js et fr.js, pour que le libellé et le routage
ne divergent jamais : deep → Ultra (judge), web → Ultra qui lit portWeb (Tavily),
fast → Lightning (nano) pour lire la question, puis les règles.
"""
import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

import logbook_chat

I18N = Path(__file__).resolve().parents[2] / "src" / "i18n"


def _val(lang: str, key: str) -> str:
    text = (I18N / f"{lang}.js").read_text(encoding="utf-8")
    m = re.search(rf"\n\s*{key}:\s*\"([^\"]+)\"", text)
    assert m, f"{lang}.{key}"
    return m.group(1)


LANGS = ("en", "fr")


@pytest.mark.parametrize("lang", LANGS)
def test_example_tiers_match_labels(lang):
    assert logbook_chat.chat_tier(_val(lang, "logbookExampleDeepQ")) == "judge"
    assert logbook_chat.chat_tier(_val(lang, "logbookExampleWebQ")) == "judge"
    assert logbook_chat.chat_tier(_val(lang, "logbookExampleFastQ")) == "fast"
    fast = logbook_chat.keyword_intent(_val(lang, "logbookExampleFastQ"))
    assert fast["intent"] == "fact" and fast["quantity"] == "wind"
    # Repli des règles si Ultra est coupé : l'escale suivante, pas « je ne sais pas ».
    web = logbook_chat.keyword_intent(_val(lang, "logbookExampleWebQ"))
    assert web["quantity"] == "next_stop"


CTX = {
    "official": {"wind": {"windKnots": 14.2, "dirFromDeg": 250}},
    "nextStop": {"name": "Funchal"},
    "portWeb": {
        "status": "ready",
        "port": "Funchal",
        "sources": [{"title": "Funchal marina news", "url": "https://example.org/funchal", "snippet": "Marina works."}],
    },
}


def _run(monkeypatch, question: str, lang: str):
    seen: list[tuple[str, str]] = []

    async def fake_cascade(system, user, client=None, **kw):
        seen.append((kw.get("tier"), user))
        if kw.get("tier") == "nano":
            return '{"intent":"fact","quantity":"wind","place":null,"when":null,"layer":null}', "nemotron-lightning"
        return "According to a web source, the marina has works.", "nemotron-ultra"

    async def fake_ctx(*_a, **_k):
        import copy
        return copy.deepcopy(CTX)

    async def no_memory(*_a, **_k):
        return []

    monkeypatch.setattr(logbook_chat, "cascade_text", fake_cascade)
    monkeypatch.setattr(logbook_chat, "build_context", fake_ctx)
    monkeypatch.setattr(logbook_chat, "similar_wx", no_memory)
    import llm_budget
    monkeypatch.setattr(llm_budget, "allow", lambda tier: True)
    out = asyncio.run(logbook_chat.answer_question(question, lang, {}, datetime.now(timezone.utc)))
    return out, seen


@pytest.mark.parametrize("lang", LANGS)
def test_deep_example_calls_ultra(monkeypatch, lang):
    out, seen = _run(monkeypatch, _val(lang, "logbookExampleDeepQ"), lang)
    tiers = [t for t, _ in seen]
    assert "judge" in tiers and "write" not in tiers
    assert out["source"] == "nemotron-ultra"


@pytest.mark.parametrize("lang", LANGS)
def test_web_example_hands_tavily_excerpts_to_ultra(monkeypatch, lang):
    out, seen = _run(monkeypatch, _val(lang, "logbookExampleWebQ"), lang)
    judge_prompts = [u for t, u in seen if t == "judge"]
    assert len(judge_prompts) == 1
    assert "portWeb" in judge_prompts[0] and "example.org/funchal" in judge_prompts[0]
    import port_web_context
    assert port_web_context.web_sources_for_response(out["context"])[0]["url"] == "https://example.org/funchal"


@pytest.mark.parametrize("lang", LANGS)
def test_fast_example_stays_on_lightning_and_rules(monkeypatch, lang):
    out, seen = _run(monkeypatch, _val(lang, "logbookExampleFastQ"), lang)
    assert [t for t, _ in seen] == ["nano"]
    assert out["source"] == "rules"
    assert "14.2" in out["answer"]


def test_build_context_attaches_port_web_for_every_question():
    src = Path(logbook_chat.__file__).read_text(encoding="utf-8")
    body = src.split("async def build_context(", 1)[1].split("\ndef ", 1)[0]
    assert "port_web_context.attach(ctx, http, now)" in body
