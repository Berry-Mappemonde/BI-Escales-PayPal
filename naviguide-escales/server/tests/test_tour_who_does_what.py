"""Visite guidée, étape « Qui fait quoi » : chaque affirmation de l'étape correspond au code.

Le texte de l'étape (src/i18n/en.js, fr.js : demoModels*) et les défauts du front
(src/components/demoWalkthrough.js : TOUR_DEFAULT_MODELS) doivent rester alignés sur
llm_budget et sur les appels réels `cascade(tier=…)`. Ce test casse si l'un bouge seul.
"""
from __future__ import annotations

import re
from pathlib import Path

import llm_budget
import story_cascade

SERVER = Path(__file__).resolve().parents[1]
SRC = SERVER.parent / "src"
TOUR_JS = SRC / "components" / "demoWalkthrough.js"


def _read(name: str) -> str:
    return (SERVER / name).read_text(encoding="utf-8")


def _js_object(src: str, name: str) -> dict[str, str]:
    m = re.search(r"export const " + name + r" = \{(.*?)\};", src, re.S)
    assert m, f"{name} absent de demoWalkthrough.js"
    return dict(re.findall(r'(\w+|"[^"]+"):\s*"([^"]+)"', m.group(1)))


def test_front_defaults_mirror_llm_budget():
    js = TOUR_JS.read_text(encoding="utf-8")
    assert _js_object(js, "TOUR_DEFAULT_MODELS") == llm_budget.DEFAULT_MODELS
    # Les rôles de l'étape couvrent tous les paliers, une seule fois.
    tiers = re.findall(r'tiers: \[([^\]]*)\]', js)
    flat = [t.strip().strip('"') for group in tiers for t in group.split(",") if t.strip()]
    assert sorted(flat) == sorted(llm_budget.TIERS)


def test_front_names_every_default_model():
    js = TOUR_JS.read_text(encoding="utf-8")
    m = re.search(r"const MODEL_NAMES = \{(.*?)\};", js, re.S)
    assert m, "MODEL_NAMES absent de demoWalkthrough.js"
    names = dict(re.findall(r'"([^"]+)":\s*"([^"]+)"', m.group(1)))
    for model in set(llm_budget.DEFAULT_MODELS.values()):
        assert model.lower() in names, model
    assert names["nvidia/nemotron-3_5-lightning"] == "Nemotron 3.5 Lightning"
    assert names["nvidia/nemotron-3.5-super-vl"] == "Nemotron 3.5 Super VL"
    assert names["nvidia/nemotron-3-ultra-550b-a55b"] == "Nemotron 3 Ultra"


def test_quick_role_claims():
    """Lightning (nano + fast) : question du journal, choix/resserrage, traduction EN, escale, conseil de route."""
    film = _read("film_script.py")
    assert re.search(r"SELECT_SYSTEM, user, tier=\"nano\"", film)
    assert re.search(r"TRIM_SYSTEM, user, tier=\"nano\"", film)
    assert re.search(r"TRANSLATE_SYSTEM,\s*\n.*\n\s*tier=\"fast\"", film)
    assert re.search(r"system, user, http, tier=\"nano\", fallback=\"\", max_tokens=PARSE_MAX_TOKENS", _read("logbook_chat.py"))
    assert 'cascade_text(system, user, client, tier="fast")' in _read("escale_api.py")
    assert re.search(r"ADVICE_SYSTEM, user, client, tier=\"fast\"", _read("voyage_api.py"))


def test_write_role_claims():
    """Super VL (write) : chapitres du film, commentaire de revue du plan, récits d'événements."""
    film = _read("film_script.py")
    assert re.search(r"WRITE_SYSTEM, user, tier=\"write\"", film)
    assert re.search(r"COMMENT_SYSTEM, user, client, tier=\"write\"", _read("plan_review.py"))
    assert story_cascade.story_tier({"type": "zee"}) == "write"


def test_deep_role_claims():
    """Ultra (deep + judge) : édite et relit le film, questions difficiles, escales et alertes majeures."""
    film = _read("film_script.py")
    assert re.search(r"EDIT_SYSTEM, user, tier=\"judge\"", film)
    assert re.search(r"JUDGE_SYSTEM, user, tier=\"judge\"", film)
    assert 'tier="judge", fallback=fallback, facts=ctx' in _read("logbook_chat.py")
    assert story_cascade.story_tier({"type": "x", "severity": "alert"}) == "deep"
    assert llm_budget.DEFAULT_MODELS["deep"] == llm_budget.DEFAULT_MODELS["judge"]


def test_ultra_edits_and_rereads_the_written_film_by_default(monkeypatch):
    """FR written films use Ultra when open; direct EN writing does not enter that branch."""
    import film_script

    for k in ("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE", "NAVIGUIDE_LLM_DAILY_USD", "NAVIGUIDE_LLM_BACKGROUND"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "on-demand")
    monkeypatch.setattr(llm_budget, "get_usage", lambda tier, day=None: llm_budget._empty())
    assert film_script.film_ultra_open() is True
    assert film_script._reread_tier() == "judge"
    assert re.search(r"if _en\(lang\) is False and film_ultra_open\(\):", _read("film_script.py"))
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE", "0")
    assert film_script.film_ultra_open() is False


def test_tavily_claims():
    """Tavily : sources web du journal de bord (port près du bateau ou prochaine escale) et du film Rédigé."""
    chat = _read("logbook_chat.py")
    assert "port_web_context.attach(ctx, http, now)" in chat
    assert "port_web_context.web_sources_for_response(" in chat
    assert "port_web_context.fetch_port_web(" in _read("film_web_context.py")


def test_status_exposes_what_the_step_reads():
    st = llm_budget.status()
    assert set(st["configuredModels"]) == set(llm_budget.TIERS)
    assert "calls" in st["tavily"]
    for t in llm_budget.TIERS:
        assert "calls" in st[t]


def test_step_copy_names_nemotron_token_factory_tavily():
    for lang in ("en", "fr"):
        src = (SRC / "i18n" / f"{lang}.js").read_text(encoding="utf-8")
        body = re.search(r'demoModelsBody: "([^"]+)"', src)
        assert body and "Nemotron" in body.group(1) and "Nebius Token Factory" in body.group(1)
        assert re.search(r'demoModelsTavily: "Tavily', src)
