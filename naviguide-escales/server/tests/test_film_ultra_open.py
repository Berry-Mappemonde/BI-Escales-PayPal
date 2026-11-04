"""Porte Ultra du film rédigé (écart n° 44) : ouverte par défaut, les freins restent des freins.

README et la visite « Qui fait quoi » affirment qu'Ultra édite et relit le film Rédigé.
Sans variable NAVIGUIDE_LLM_DAILY_TOKENS_*, la porte doit suivre le plafond par défaut de
llm_budget (DEFAULT_CAPS["judge"]) au lieu de rester fermée. Aucun appel réseau ici.
"""
from __future__ import annotations

import pytest

import llm_budget
from film_script import _reread_tier, film_ultra_open

ENV = "NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in ("NAVIGUIDE_LLM_DAILY_TOKENS_NANO", "NAVIGUIDE_LLM_DAILY_TOKENS_FAST",
              "NAVIGUIDE_LLM_DAILY_TOKENS_WRITE", "NAVIGUIDE_LLM_DAILY_TOKENS_DEEP", ENV,
              "NAVIGUIDE_LLM_DAILY_USD", "NAVIGUIDE_LLM_BACKGROUND"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "on-demand")
    # Compteur du jour vide, sans toucher au stock réel.
    monkeypatch.setattr(llm_budget, "get_usage", lambda tier, day=None: llm_budget._empty())


def _cap_reached(monkeypatch):
    def used(tier, day=None):
        out = llm_budget._empty()
        out["tokens"] = llm_budget.daily_cap(tier)
        return out
    monkeypatch.setattr(llm_budget, "get_usage", used)


def test_absent_variable_opens_ultra_by_default():
    assert llm_budget.daily_cap("judge") == llm_budget.DEFAULT_CAPS["judge"] > 0
    assert film_ultra_open() is True
    assert _reread_tier() == "judge"


def test_empty_variable_is_the_default(monkeypatch):
    monkeypatch.setenv(ENV, "  ")
    assert film_ultra_open() is True


def test_explicit_zero_is_the_operator_switch(monkeypatch):
    monkeypatch.setenv(ENV, "0")
    assert film_ultra_open() is False
    assert _reread_tier() == "reread"
    assert llm_budget.normalize_tier(_reread_tier()) == "write"  # Super VL


def test_negative_value_closes(monkeypatch):
    monkeypatch.setenv(ENV, "-5")
    assert film_ultra_open() is False


@pytest.mark.parametrize("bad", ["off", "250k", "1e5", "abc"])
def test_invalid_value_closes(monkeypatch, bad):
    """Choix documenté : une valeur incomprise ferme Ultra (pas de dépense sur un doute)."""
    monkeypatch.setenv(ENV, bad)
    assert film_ultra_open() is False
    assert _reread_tier() == "reread"


def test_positive_value_opens(monkeypatch):
    monkeypatch.setenv(ENV, "250000")
    assert film_ultra_open() is True
    assert _reread_tier() == "judge"


def test_daily_cap_reached_closes_by_default(monkeypatch):
    _cap_reached(monkeypatch)
    assert film_ultra_open() is False
    assert _reread_tier() == "reread"


def test_daily_cap_reached_closes_with_explicit_value(monkeypatch):
    monkeypatch.setenv(ENV, "1000")
    _cap_reached(monkeypatch)
    assert film_ultra_open() is False


def test_mode_off_never_opens(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "off")
    assert film_ultra_open() is False
    monkeypatch.setenv(ENV, "250000")
    assert film_ultra_open() is False
    assert _reread_tier() == "reread"


def test_background_never_opens(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_LLM_BACKGROUND", "1")
    assert film_ultra_open() is False


def test_dollar_cap_closes(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_USD", "0.000001")
    assert film_ultra_open() is False
