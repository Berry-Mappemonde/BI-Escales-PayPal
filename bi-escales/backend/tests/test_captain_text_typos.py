"""Captain copy typos: spacing, French elision, EN fund-label prompt."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales import captain
from app.escales.captain import (
    _chat_system_en,
    _compose_chat_reply,
    _fit_words,
    _fund_place_label,
    _french_de_elision,
    _public_rule,
    _signature,
)


def test_fit_words_inserts_space_before_la_promesse_and_a_pledge():
    fr = _fit_words(
        "Merci pour votre soutien.",
        [_public_rule("fr"), _signature("fr")],
    )
    assert ".La promesse" not in fr
    assert ". La promesse" in fr
    en = _fit_words(
        "Thanks for supporting the leg.",
        [_public_rule("en"), _signature("en")],
    )
    assert ".A pledge" not in en
    assert ". A pledge" in en


def test_french_de_elision_before_vowel_and_h():
    assert _french_de_elision("de Ajaccio") == "d'Ajaccio"
    assert _french_de_elision("de La Rochelle") == "de La Rochelle"
    assert _fund_place_label("dep-ajaccio-corse", "fr").casefold().startswith("la caisse d'ajaccio")


def test_en_chat_system_omits_fund_label_boilerplate():
    system = _chat_system_en()
    assert "the fund is not specified" not in system.casefold()
    assert "the fund label is the fund at" not in system.casefold()
    assert "fund_label" in system
    assert ", the fund," not in system


def test_compose_chat_reply_drops_fund_label_filler_sentences():
    suggested = {
        "amount_eur": "10.00",
        "currency": "EUR",
        "description": "10 sponsored miles",
        "milestone_id": "dep-ajaccio",
        "kind": "mile",
        "intent": "AUTHORIZE",
    }
    model = (
        "The fund label is the fund at Ajaccio. The fund is not specified. "
        "Ten miles for Ajaccio."
    )
    reply = _compose_chat_reply(model, suggested, "", "en", treasurer=False, ask_escale=False)
    lowered = reply.casefold()
    assert "the fund label is the fund at" not in lowered
    assert "the fund is not specified" not in lowered
    assert "10 sponsored miles" in reply
