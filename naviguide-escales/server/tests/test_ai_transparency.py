"""Machine-readable flags on language-model payloads."""
from pathlib import Path

from ai_transparency import enrich_llm_payload, is_ai_generated_source, text_is_ai_generated, transparency_fields

_SERVER = Path(__file__).resolve().parents[1]


def test_is_ai_generated_source():
    assert is_ai_generated_source("rules") is False
    assert is_ai_generated_source("budget") is False
    assert is_ai_generated_source("") is False
    assert is_ai_generated_source(None) is False
    assert is_ai_generated_source("nemotron-super+local") is False
    assert is_ai_generated_source("nemotron-super") is True
    assert is_ai_generated_source("nemotron-lightning") is True
    assert is_ai_generated_source("nemotron-nano") is True
    assert is_ai_generated_source("nemotron-super-token-factory") is True
    assert is_ai_generated_source("cache") is True
    assert is_ai_generated_source("openrouter") is True
    assert is_ai_generated_source("claude") is True
    assert is_ai_generated_source("nvidia-nim") is True


def test_enrich_llm_payload_adds_flags():
    out = enrich_llm_payload({"status": "ready", "text": "Hi", "source": "nemotron-ultra"})
    assert out["ai_generated"] is True
    assert out["ai_model"] == "nemotron-ultra"
    assert out["model"] == "nemotron-ultra"
    assert out["generated_at"]
    rules = enrich_llm_payload({"status": "ready", "text": "Hi", "source": "rules"})
    assert rules["ai_generated"] is False
    assert "ai_model" not in rules
    assert "generated_at" not in rules
    assert "model" not in rules


def test_local_fallback_and_empty_text_are_not_generated():
    local = enrich_llm_payload({
        "status": "ready",
        "text": "Phrase locale.",
        "source": "nemotron-super",
        "engine": "nemotron-super+local",
    })
    assert local["ai_generated"] is False
    assert "ai_model" not in local
    empty = enrich_llm_payload({"status": "failed", "text": None, "source": "nemotron-super"})
    assert empty["ai_generated"] is False


def test_cache_keeps_the_original_model():
    hit = enrich_llm_payload({
        "status": "ready",
        "text": "Récit en cache.",
        "source": "cache",
        "engine": "cache:nemotron-super",
        "cachedAt": 1_700_000_000,
    })
    assert hit["ai_generated"] is True
    assert hit["ai_model"] == "nemotron-super"
    assert hit["model"] == "nemotron-super"
    assert hit["generated_at"].startswith("2023-")
    rules_hit = enrich_llm_payload({
        "status": "ready",
        "text": "Règles.",
        "source": "cache",
        "engine": "cache:rules",
    })
    assert rules_hit["ai_generated"] is False
    assert text_is_ai_generated({"text": "x", "source": "cache", "engine": "cache"}) is True


def test_chat_answer_uses_answer_and_existing_timestamp():
    out = enrich_llm_payload({
        "status": "ready",
        "answer": "Stay at the quay.",
        "source": "nemotron-ultra",
        "t": "2026-05-15T08:00:00Z",
    })
    assert out["ai_generated"] is True
    assert out["ai_model"] == "nemotron-ultra"
    assert out["generated_at"] == "2026-05-15T08:00:00Z"
    again = enrich_llm_payload(out)
    assert again["generated_at"] == "2026-05-15T08:00:00Z"
    assert again["model"] == "nemotron-ultra"


def test_transparency_fields_rules():
    assert transparency_fields("rules") == {"ai_generated": False}
    flagged = transparency_fields("openrouter")
    assert flagged["ai_generated"] is True
    assert flagged["ai_model"] == "openrouter"
    assert flagged["model"] == "openrouter"


def test_writers_enrich_their_payloads():
    story = (_SERVER / "story_cascade.py").read_text(encoding="utf-8")
    chat = (_SERVER / "logbook_chat.py").read_text(encoding="utf-8")
    escale = (_SERVER / "escale_api.py").read_text(encoding="utf-8")
    main = (_SERVER / "main.py").read_text(encoding="utf-8")
    assert "@with_ai_transparency" in story
    assert "async def write_story" in story
    assert "enrich_llm_payload" in chat
    assert "@with_ai_transparency" in escale
    assert "async def write_paragraph" in escale
    assert "enrich_llm_payload" in main
