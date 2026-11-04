"""Idée n° 3 : reçu « Comment ce film a été fait » — seulement des compteurs mesurés."""
from __future__ import annotations

import asyncio
import json
import re

import official_store
import tavily_client
from story_cascade import CascadeResult
from tests.test_film_web_context import NOW, _install


def _counting_cascade(log):
    async def cascade(system, user, **kw):
        tier = kw.get("tier") or "write"
        log.append(tier)
        model = {
            "write": "nvidia/Nemotron-3.5-Super-VL",
            "fast": "nvidia/Nemotron-3.5-Lightning",
        }.get(tier, "nvidia/Nemotron-3-Ultra")
        if "real stops" in (system or ""):
            return CascadeResult('{"ok": true, "faults": []}', "nemotron-super", model=model, tier=tier)
        match = re.search(r"sentences=(\[.*\])", user or "", re.S)
        sents = json.loads(match.group(1)) if match else ["ok."]
        text = " ".join(s.replace("quitte", "laisse", 1) for s in sents)
        return CascadeResult(text, "nemotron-super", model=model, tier=tier)
    return cascade


def test_receipt_counts_only_real_calls(tmp_path, monkeypatch):
    _install(tmp_path, monkeypatch)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    async def no_search(*_a, **_k):
        raise AssertionError("pas de clé, pas d'appel Tavily")

    monkeypatch.setattr(tavily_client, "search", no_search)
    log: list[str] = []
    asyncio.run(official_store.write_film_on_click("fr", 150, cascade=_counting_cascade(log), now=NOW))

    written = official_store.serve_film("fr", 150, style="written")
    assert written["hasWritten"] is True
    rc = written["receipt"]
    assert written["chapters"]
    assert all(ch.get("served_model") and ch.get("served_source") and ch.get("served_tier") for ch in written["chapters"])
    assert {ch["served_model"] for ch in written["chapters"]} <= {m["model"] for m in rc["models"]}
    assert all("served_model" not in ch for ch in official_store.serve_film("fr", 150, style="raw")["chapters"])
    # Chaque appel de la cascade est compté une fois, ni plus ni moins.
    assert rc["llmCalls"] == len(log) and rc["llmCalls"] > 0
    assert sum(m["calls"] for m in rc["models"]) == len(log)
    assert rc["cacheHits"] == 0 and rc["ruleFallbacks"] == 0
    assert {m["model"] for m in rc["models"]} <= {
        "nvidia/Nemotron-3.5-Super-VL", "nvidia/Nemotron-3.5-Lightning", "nvidia/Nemotron-3-Ultra",
    }
    assert rc["rewritten"] >= 1 and rc["fallen"] == 0
    assert rc["super"] == 1
    assert rc["reread"] == "pass"
    assert "faults" not in rc  # relecture réussie : aucun défaut inventé
    assert rc["at"].startswith("2026-09-26")
    # Le brut ne porte jamais de reçu.
    assert "receipt" not in official_store.serve_film("fr", 150, style="raw")


def test_receipt_counts_cache_and_rules_apart():
    calls = [
        {"tier": "write", "source": "nemotron-super", "model": "m-super", "cache": False},
        {"tier": "write", "source": "nemotron-super", "model": "m-super", "cache": True},
        {"tier": "fast", "source": "rules", "model": "", "cache": False},
        {"tier": "fast", "source": "budget", "model": "", "cache": False},
    ]
    stats = {"rewritten": 3, "fallen": 2, "reread": "pass", "reread_en": "fail",
             "faults": ["a", "b"], "judge_failed": ["c1"], "reviewed": False, "source": "x"}
    rc = official_store.film_receipt(calls, stats, NOW)
    assert rc["llmCalls"] == 1 and rc["cacheHits"] == 1 and rc["ruleFallbacks"] == 2
    assert rc["models"] == [{"model": "m-super", "source": "nemotron-super", "tier": "write", "calls": 2, "cached": 1}]
    assert rc["rewritten"] == 3 and rc["fallen"] == 2
    assert rc["faults"] == 2 and rc["judgeFailed"] == 1 and rc["reviewed"] is False
    assert rc["reread_en"] == "fail"
    assert "source" not in rc  # rien qui ne soit pas un compteur
    # EN traduit ensuite : on ajoute les appels Lightning au reçu FR.
    en = official_store.film_receipt(
        [{"tier": "fast", "source": "nemotron-lightning", "model": "m-light", "cache": False}],
        {"lightning": 1}, NOW, base=rc,
    )
    assert en["llmCalls"] == 2 and en["cacheHits"] == 1 and en["ruleFallbacks"] == 2
    assert en["rewritten"] == 3 and en["lightning"] == 1
    assert sum(m["calls"] for m in en["models"]) == 3


def test_recorder_passes_result_through():
    async def cascade(system, user, **kw):
        return CascadeResult("texte", "nemotron-ultra", model="m-ultra", tier="deep")

    wrapped, calls = official_store._receipt_recorder(cascade)
    out = asyncio.run(wrapped("s", "u", tier="deep"))
    assert tuple(out) == ("texte", "nemotron-ultra")
    assert calls == [{"tier": "deep", "source": "nemotron-ultra", "model": "m-ultra", "cache": False}]
