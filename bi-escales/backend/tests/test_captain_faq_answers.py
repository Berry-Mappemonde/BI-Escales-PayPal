"""Audit item 2: the Captain's suggested questions each get their own answer.

"When am I charged?" and "What happens if a stop is cancelled?" both used to return
"Which stopover? Name the stop and I will compute the pledge." followed by the capture rule.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.captain import (
    CANCELLED_STOP_RULE_EN,
    CANCELLED_STOP_RULE_FR,
    _is_cancelled_stop_question,
    _is_capture_rule_question,
    chat,
)
from app.escales.departure_clock import CAPTURE_RULES_EN, CAPTURE_RULES_FR
from app.escales.pledges import reset_ledger


@pytest.fixture(autouse=True)
def memory(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.delenv("ESCALES_LLM_ENABLED", raising=False)
    reset_ledger()
    yield
    reset_ledger()


def ask(question: str, lang: str) -> dict:
    return asyncio.run(chat(question, lang=lang))


@pytest.mark.parametrize(
    "question, lang, rule",
    [
        ("When am I charged?", "en", CAPTURE_RULES_EN),
        ("When will I be charged?", "en", CAPTURE_RULES_EN),
        ("when do I pay", "en", CAPTURE_RULES_EN),
        ("Quand suis-je débité ?", "fr", CAPTURE_RULES_FR),
        ("Quand serai-je prélevé ?", "fr", CAPTURE_RULES_FR),
    ],
)
def test_when_am_i_charged_gets_the_capture_rule_with_no_question_back(question, lang, rule):
    reply = ask(question, lang)
    assert rule in reply["reply"]
    assert "Which stopover" not in reply["reply"] and "Quelle escale" not in reply["reply"]
    assert reply["rule_by_design"] is True
    assert reply["suggested_pledge"] is None and reply["cart"] is None


@pytest.mark.parametrize(
    "question, lang, rule",
    [
        ("What happens if a stop is cancelled?", "en", CANCELLED_STOP_RULE_EN),
        ("What happens if a stop is canceled?", "en", CANCELLED_STOP_RULE_EN),
        ("If the stop is cancelled, do I pay?", "en", CANCELLED_STOP_RULE_EN),
        ("Que se passe-t-il si une escale est annulée ?", "fr", CANCELLED_STOP_RULE_FR),
        ("Et si l'étape est annulée ?", "fr", CANCELLED_STOP_RULE_FR),
    ],
)
def test_a_cancelled_stop_question_gets_the_cancellation_rule(question, lang, rule):
    reply = ask(question, lang)
    assert rule in reply["reply"]
    assert "Which stopover" not in reply["reply"] and "Quelle escale" not in reply["reply"]
    assert "trésorier" not in reply["reply"].lower() or "revue du trésorier" not in reply["reply"]
    assert reply["rule_by_design"] is True
    assert reply["model_source"] == {"provider": "rules", "model": ""}
    assert reply["suggested_pledge"] is None and reply["cart"] is None


def test_the_two_suggested_questions_no_longer_share_one_answer():
    for lang, charged, cancelled in (
        ("en", "When am I charged?", "What happens if a stop is cancelled?"),
        ("fr", "Quand suis-je débité ?", "Que se passe-t-il si une escale est annulée ?"),
    ):
        assert ask(charged, lang)["reply"] != ask(cancelled, lang)["reply"]


def test_the_cancellation_answer_says_what_the_supporter_pays():
    assert "You pay nothing" in ask("What happens if a stop is cancelled?", "en")["reply"]
    assert "Vous ne payez rien" in ask("Que se passe-t-il si une escale est annulée ?", "fr")["reply"]


@pytest.mark.parametrize(
    "question",
    ["Where is the boat?", "Sponsor 20 miles near Mayotte", "When will the boat arrive in Ajaccio?", "How much is the Crew membership?"],
)
def test_other_questions_are_not_taken_for_a_cancellation_or_charge_question(question):
    assert _is_cancelled_stop_question(question) is False
    assert _is_capture_rule_question(question) is False


def test_a_pledge_request_stays_a_pledge():
    reply = ask("Sponsor 20 miles near Mayotte", "en")
    assert reply["suggested_pledge"]["amount_eur"] == "20.00"
    assert CANCELLED_STOP_RULE_EN not in reply["reply"]


def test_an_order_to_void_is_not_answered_with_the_capture_rule():
    # The existing guard: "void" or "annuler" in the message is not a "when" question.
    assert _is_capture_rule_question("When am I charged if you void it?") is False
