"""Captain voyage questions: position, next stop and ETA from the schedule only."""
import asyncio

import pytest

from app.core import llm
from app.escales import ledger
from app.escales.captain import chat
from app.escales.voyage_answers import voyage_question_kind

BEFORE_DEPARTURE = "2026-11-12T08:00:00Z"
AT_SEA = "2026-11-20T08:00:00Z"
NEAR_AJACCIO = "2026-11-28T20:00:00Z"
IN_AJACCIO = "2026-11-30T08:00:00Z"
AFTER_RETURN = "2027-09-01T08:00:00Z"


@pytest.fixture(autouse=True)
def rules_only(monkeypatch):
    monkeypatch.setenv("ESCALES_TOOLKIT_ENABLED", "0")
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.setattr(ledger, "_ledger", ledger.MemoryLedger())

    def no_model(*_a, **_kw):
        raise AssertionError("a voyage question must not reach a model")

    monkeypatch.setattr(llm, "has_llm", lambda *a, **kw: False)
    monkeypatch.setattr(llm, "ask_text", no_model)


def ask(monkeypatch, message, lang, now):
    monkeypatch.setenv("ESCALES_CLOCK_NOW", now)
    return asyncio.run(chat(message, lang=lang))


def assert_voyage_rule(result, lang):
    assert result["rule_by_design"] is True
    assert result["rule_source"] == "voyage_schedule"
    assert result["rule_label"] == (
        "From the voyage schedule" if lang == "en" else "D'après le calendrier du voyage"
    )
    assert result["model_label"] == "rules"
    assert result["model_source"] == {"provider": "rules", "model": ""}
    assert result["suggested_pledge"] is None
    assert result["cart"] is None
    assert result["trace_id"] is None


@pytest.mark.parametrize("message,kind", [
    ("Where is the boat?", "where"),
    ("where's the ship now", "where"),
    ("Où est le bateau ?", "where"),
    ("Ou est le bateau", "where"),
    ("What is the next stop?", "next"),
    ("Quelle est la prochaine escale ?", "next"),
    ("When do you arrive at Papeete?", "eta"),
    ("When will the boat reach Ajaccio", "eta"),
    ("Quand arrivez-vous à Nouméa ?", "eta"),
    ("Quand est-ce que le bateau arrive à Cayenne ?", "eta"),
    ("When is the money captured?", None),
    ("Sponsor 20 miles near Mayotte", None),
])
def test_question_kind(message, kind):
    assert voyage_question_kind(message) == kind


# Before departure: the clock pinned at the voyage origin.

def test_where_before_departure_en(monkeypatch):
    result = ask(monkeypatch, "Where is the boat?", "en", BEFORE_DEPARTURE)
    assert_voyage_rule(result, "en")
    assert "has not departed yet" in result["reply"]
    assert "12 November 2026" in result["reply"]
    assert "Next stop: La Rochelle, scheduled arrival on 12 November 2026 at 12:00 UTC" in result["reply"]
    assert result["reply"].endswith("— The captain")


def test_where_before_departure_fr(monkeypatch):
    result = ask(monkeypatch, "Où est le bateau ?", "fr", BEFORE_DEPARTURE)
    assert_voyage_rule(result, "fr")
    assert "pas encore parti" in result["reply"]
    assert "12 novembre 2026" in result["reply"]
    assert "Prochaine escale : La Rochelle, arrivée prévue le 12 novembre 2026 à 12:00 UTC" in result["reply"]
    assert result["reply"].endswith("— Le capitaine")


@pytest.mark.parametrize("lang,message,expected", [
    ("en", "What is the next stop?", "Next stop: La Rochelle"),
    ("fr", "Quelle est la prochaine escale ?", "Prochaine escale : La Rochelle"),
])
def test_next_stop_before_departure(monkeypatch, lang, message, expected):
    result = ask(monkeypatch, message, lang, BEFORE_DEPARTURE)
    assert_voyage_rule(result, lang)
    assert expected in result["reply"]
    assert ("has not departed yet" if lang == "en" else "pas encore parti") in result["reply"]


@pytest.mark.parametrize("lang,message,expected", [
    ("en", "When do you arrive at Nouméa?", "Scheduled arrival at Nouméa (Nouvelle-Calédonie): on 9 April 2027 at 01:47 UTC"),
    ("fr", "Quand arrivez-vous à Nouméa ?", "Arrivée prévue à Nouméa (Nouvelle-Calédonie) : le 9 avril 2027 à 01:47 UTC"),
])
def test_eta_before_departure(monkeypatch, lang, message, expected):
    result = ask(monkeypatch, message, lang, BEFORE_DEPARTURE)
    assert_voyage_rule(result, lang)
    assert expected in result["reply"]


# Underway and in port.

@pytest.mark.parametrize("lang,message,expected", [
    ("en", "Where is the boat?", "The boat is underway from La Rochelle to Ajaccio (Corse)."),
    ("fr", "Où est le bateau ?", "Le bateau fait route de La Rochelle vers Ajaccio (Corse)."),
])
def test_where_at_sea(monkeypatch, lang, message, expected):
    result = ask(monkeypatch, message, lang, AT_SEA)
    assert_voyage_rule(result, lang)
    assert expected in result["reply"]


@pytest.mark.parametrize("lang,expected", [
    ("en", "Last logbook position on 28 November 2026 at 14:02 UTC"),
    ("fr", "Dernière position du journal de bord le 28 novembre 2026 à 14:02 UTC"),
])
def test_where_uses_the_navigation_logbook(monkeypatch, lang, expected):
    message = "Where is the boat?" if lang == "en" else "Où est le bateau ?"
    result = ask(monkeypatch, message, lang, NEAR_AJACCIO)
    assert expected in result["reply"]


@pytest.mark.parametrize("lang,message,expected", [
    ("en", "Where is the boat?", "The boat is in port at Ajaccio (Corse) since 29 November 2026 at 02:02 UTC. Departure on 2 December 2026 at 02:02 UTC."),
    ("fr", "Où est le bateau ?", "Le bateau est au port à Ajaccio (Corse) depuis le 29 novembre 2026 à 02:02 UTC. Départ le 2 décembre 2026 à 02:02 UTC."),
])
def test_where_in_port(monkeypatch, lang, message, expected):
    result = ask(monkeypatch, message, lang, IN_AJACCIO)
    assert_voyage_rule(result, lang)
    assert expected in result["reply"]


@pytest.mark.parametrize("lang,message,expected", [
    ("en", "What is the next stop?", "Next stop: Fort-de-France (Martinique), scheduled arrival on 30 December 2026 at 08:34 UTC."),
    ("fr", "Quelle est la prochaine escale ?", "Prochaine escale : Fort-de-France (Martinique), arrivée prévue le 30 décembre 2026 à 08:34 UTC."),
])
def test_next_stop_in_port(monkeypatch, lang, message, expected):
    result = ask(monkeypatch, message, lang, IN_AJACCIO)
    assert_voyage_rule(result, lang)
    assert expected in result["reply"]


@pytest.mark.parametrize("lang,message,expected", [
    ("en", "When will the boat reach Ajaccio?", "The boat arrived at Ajaccio (Corse) on 29 November 2026 at 02:02 UTC."),
    ("fr", "Quand arrivez-vous à Ajaccio ?", "Le bateau est arrivé à Ajaccio (Corse) le 29 novembre 2026 à 02:02 UTC."),
])
def test_eta_for_a_past_stop(monkeypatch, lang, message, expected):
    result = ask(monkeypatch, message, lang, IN_AJACCIO)
    assert expected in result["reply"]


@pytest.mark.parametrize("lang,message,expected", [
    ("en", "When do you arrive at Papeete?", "Scheduled arrival at Papeete (Polynésie française): on 12 March 2027 at 15:01 UTC."),
    ("fr", "Quand arrivez-vous à Papeete ?", "Arrivée prévue à Papeete (Polynésie française) : le 12 mars 2027 à 15:01 UTC."),
])
def test_eta_for_a_named_stop(monkeypatch, lang, message, expected):
    result = ask(monkeypatch, message, lang, AT_SEA)
    assert_voyage_rule(result, lang)
    assert expected in result["reply"]


def test_eta_for_la_rochelle_includes_the_return(monkeypatch):
    result = ask(monkeypatch, "When do you arrive at La Rochelle?", "en", AT_SEA)
    assert "La Rochelle (retour): on 27 August 2027 at 08:23 UTC" in result["reply"]


@pytest.mark.parametrize("lang,message,expected", [
    ("en", "When do you arrive at Dakar?", 'I cannot find "Dakar" on the voyage schedule. The stops are:'),
    ("fr", "Quand arrivez-vous à Dakar ?", "Je ne trouve pas « Dakar » dans le calendrier du voyage. Les escales sont :"),
])
def test_unknown_stop_lists_the_real_stops(monkeypatch, lang, message, expected):
    result = ask(monkeypatch, message, lang, AT_SEA)
    assert_voyage_rule(result, lang)
    reply = result["reply"]
    assert expected in reply
    for name in ("Ajaccio (Corse)", "Papeete (Polynésie française)", "Nouméa (Nouvelle-Calédonie)"):
        assert name in reply
    assert "2026" not in reply and "2027" not in reply, "no invented date for an unknown stop"


@pytest.mark.parametrize("lang,message,expected", [
    ("en", "Where is the boat?", "The voyage is complete"),
    ("fr", "Où est le bateau ?", "Le voyage est terminé"),
])
def test_after_the_return(monkeypatch, lang, message, expected):
    result = ask(monkeypatch, message, lang, AFTER_RETURN)
    assert expected in result["reply"]


def test_never_mentions_a_may_departure(monkeypatch):
    for now in (BEFORE_DEPARTURE, AT_SEA, IN_AJACCIO):
        for message, lang in (("Where is the boat?", "en"), ("Où est le bateau ?", "fr")):
            reply = ask(monkeypatch, message, lang, now)["reply"]
            assert " May " not in reply and " mai " not in reply


def test_a_priced_pledge_is_not_hijacked(monkeypatch):
    result = ask(monkeypatch, "Sponsor 20 miles to the next stop near Ajaccio", "en", AT_SEA)
    assert result.get("rule_source") != "voyage_schedule"
