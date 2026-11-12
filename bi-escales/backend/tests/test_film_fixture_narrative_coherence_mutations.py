"""Prove narrative coherence checks fail on representative fixture mutations."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tests.test_film_fixture_narrative_coherence import (
    _cabin_sea_bounds,
    run_film_fixture_narrative_coherence,
)
from tests.film_cabin_schedule import fixture_tb_matches_cabin

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "naviguide-escales/server/tests/fixtures"
CABIN = Path(__file__).resolve().parents[1] / "app/escales/cabin_legs.json"


def _payload() -> dict:
    return json.loads((FIXTURES / "film_integral_written_2026-10-29.json").read_text(encoding="utf-8"))


def _run_mutated(mutator, *, label: str) -> None:
    cabin = json.loads(CABIN.read_text(encoding="utf-8"))
    payload = _payload()
    mutator(payload)
    with pytest.raises(AssertionError):
        run_film_fixture_narrative_coherence(
            payload,
            fixture_name=f"mutation:{label}",
            cabin_bounds=_cabin_sea_bounds(cabin),
            expected_tb=fixture_tb_matches_cabin(cabin),
        )


def _leg(payload: dict, lang: str, leg_id: str) -> dict:
    for leg in payload[lang]["chapters"]:
        if leg.get("id") == leg_id:
            return leg
    raise KeyError(leg_id)


@pytest.mark.parametrize(
    "label,mutator",
    [
        (
            "shift_departure_date",
            lambda p: _leg(p, "fr", "leg-3").update(
                {"text": _leg(p, "fr", "leg-3")["text"].replace("Le 5 janvier", "Le 3 janvier", 1)}
            ),
        ),
        (
            "shift_arrival_date",
            lambda p: _leg(p, "fr", "leg-4").update(
                {"text": _leg(p, "fr", "leg-4")["text"].replace("le 10 janvier", "le 9 janvier", 1)}
            ),
        ),
        (
            "invented_day_month",
            lambda p: _leg(p, "fr", "leg-2").update(
                {"text": _leg(p, "fr", "leg-2")["text"] + " Le 15 mars, cap au nord."}
            ),
        ),
        (
            "swap_fr_en_sea_days",
            lambda p: _leg(p, "fr", "leg-1").update(
                {"text": _leg(p, "fr", "leg-1")["text"].replace("une trentaine de jours de mer", "six jours de mer", 1)}
            ),
        ),
        (
            "change_497_nm",
            lambda p: _leg(p, "fr", "leg-7").update(
                {"text": _leg(p, "fr", "leg-7")["text"].replace("497 milles", "498 milles", 1)}
            ),
        ),
        (
            "reintroduce_4x18h_split",
            lambda p: _leg(p, "fr", "leg-6").update({"tA": "2027-01-18T00:00:00Z"}),
        ),
        (
            "reintroduce_leg7_three_days_fr",
            lambda p: _leg(p, "fr", "leg-7").update(
                {"text": _leg(p, "fr", "leg-7")["text"].replace("moins d'un jour de mer", "trois jours de mer", 1)}
            ),
        ),
        (
            "reintroduce_leg7_three_days_en",
            lambda p: _leg(p, "en", "leg-7").update(
                {"text": _leg(p, "en", "leg-7")["text"].replace("less than a day at sea", "three days at sea", 1)}
            ),
        ),
        (
            "reintroduce_leg8_five_days",
            lambda p: _leg(p, "fr", "leg-8").update(
                {"text": _leg(p, "fr", "leg-8")["text"].replace("deux jours de mer", "cinq jours de mer", 1)}
            ),
        ),
        (
            "reintroduce_de_halifax",
            lambda p: _leg(p, "fr", "leg-9").update(
                {"text": _leg(p, "fr", "leg-9")["text"].replace("d'Halifax", "de Halifax", 1)}
            ),
        ),
        (
            "reintroduce_2027_08_26",
            lambda p: _leg(p, "fr", "leg-17")
            .setdefault("anchors", [])
            .append(
                {
                    "charIdx": 80,
                    "t": "2027-08-26T04:23:32Z",
                    "place": "Pointe d'Arçay",
                    "kind": "alert-on",
                }
            ),
        ),
        (
            "duplicate_pointe_arcay",
            lambda p: _leg(p, "fr", "leg-17").update(
                {
                    "text": _leg(p, "fr", "leg-17")["text"]
                    + " Puis, le bateau passe près de l'aire marine protégée Pointe d'Arçay."
                }
            ),
        ),
        (
            "change_tA",
            lambda p: _leg(p, "fr", "leg-11").update({"tA": "2027-03-01T00:00:00Z"}),
        ),
        (
            "change_tB",
            lambda p: _leg(p, "fr", "leg-12").update({"tB": "2027-04-01T00:00:00Z"}),
        ),
        (
            "break_charIdx",
            lambda p: _leg(p, "fr", "leg-1")["anchors"].__setitem__(0, {**_leg(p, "fr", "leg-1")["anchors"][0], "charIdx": 99999}),
        ),
        (
            "reintroduce_le_august",
            lambda p: _leg(p, "en", "leg-10").update(
                {"text": _leg(p, "en", "leg-10")["text"].replace("On January", "Le August", 1)}
            ),
        ),
    ],
)
def test_coherence_rejects_mutation(label: str, mutator) -> None:
    _run_mutated(mutator, label=label)
