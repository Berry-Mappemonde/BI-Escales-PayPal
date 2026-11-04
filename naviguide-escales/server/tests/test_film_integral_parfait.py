"""Film intégral au « now » réel (29/10/2026) : deux défauts vérifiables du brut.

1. « à l'équateur » dit à 4,95° N (Dégrad des Cannes, Cayenne) et à 5,0° N
   (Pacifique, après Panama) : le bateau n'a pas coupé l'équateur.
2. « Le 27 octobre, le bateau longe Mata-Utu. […] Arrivée à Mata-Utu » et
   « le bateau longe Dégrad des Cannes […] amarré à la marina de Dégrad des
   Cannes » : on ne longe pas le port où l'on arrive.
"""
from climo_events import EQUATOR_BAND_DEG, _place_phrase
import film_script as fs
from film_script import _coast_is_arrival, spoken_sea_days


def test_equator_only_near_the_line():
    assert EQUATOR_BAND_DEG <= 2.0
    assert _place_phrase(0.4, -50.0, "fr") == "à l'équateur"
    assert _place_phrase(-1.9, -30.0, "en") == "at the equator"
    for lat, lon in ((4.95, -52.35), (5.0, -86.33), (-4.9, -100.0), (3.0, -40.0)):
        assert "équateur" not in _place_phrase(lat, lon, "fr"), (lat, lon)
        assert "equator" not in _place_phrase(lat, lon, "en"), (lat, lon)


def _coast(name):
    return {"kind": "coast", "title": name, "fact": name, "ports": [name]}


def test_coast_naming_destination_is_dropped():
    assert _coast_is_arrival(_coast("Mata-Utu"), "Mata-Utu (Wallis-et-Futuna)", [], None, "fr")
    assert _coast_is_arrival(_coast("Mata-Utu"), "Mata-Utu", [], None, "en")


def test_coast_naming_arrival_marina_is_dropped():
    marina = {"kind": "marina", "title": "Dégrad des Cannes", "fact": "Dégrad des Cannes",
              "lat": 4.85, "lon": -52.27}
    dest = {"name": "Cayenne (Guyane)", "lat": 4.93, "lon": -52.33}
    assert _coast_is_arrival(_coast("Dégrad des Cannes"), "Cayenne (Guyane)", [marina], dest, "fr")
    assert not _coast_is_arrival(_coast("Cannes"), "Cayenne (Guyane)", [marina], dest, "fr")


def test_coast_arrival_harbor_errors_are_not_hidden(monkeypatch):
    import pytest

    def fail(*args, **kwargs):
        raise RuntimeError("harbor lookup failed")

    monkeypatch.setattr(fs, "_arrival_harbor", fail)
    with pytest.raises(RuntimeError, match="harbor lookup failed"):
        _coast_is_arrival(_coast("Dégrad des Cannes"), "Cayenne", [], {"name": "Cayenne"}, "fr")


def test_other_coasts_are_kept():
    assert not _coast_is_arrival(_coast("Pago Pago"), "Mata-Utu (Wallis-et-Futuna)", [], None, "fr")
    assert not _coast_is_arrival(_coast("Paramaribo"), "Cayenne (Guyane)", [], {"name": "Cayenne (Guyane)"}, "fr")
    assert not _coast_is_arrival(_coast("Saint-Denis"), "Saint-Gilles (La Réunion)", [], None, "fr")


def test_short_hop_is_not_a_day_at_sea():
    # Gustavia → Marigot : 41 milles à 8 nœuds = 0,2 jour.
    assert spoken_sea_days(0.2, "fr") == "moins d'un jour de mer"
    assert spoken_sea_days(0.2, "en") == "less than a day at sea"
    assert spoken_sea_days(0.9, "fr") == "un jour de mer"
    assert spoken_sea_days(1.0, "en") == "one day at sea"


def test_reread_knows_halifax_from_chapters_when_voyage_marks_lack_it(monkeypatch):
    """Le voyage officiel n'a Halifax ni dans marks ni dans clock.marks : la relecture
    simulée ne doit pas rejeter le film pour « absent » sur l'arrivée à Halifax."""
    import voyage_store

    marks = [{"name": n} for n in (
        "Saint-Maur (Berry, Indre)", "La Rochelle", "Ajaccio (Corse)",
        "Fort-de-France (Martinique)", "Pointe-à-Pitre (Guadeloupe)",
        "Gustavia (Saint-Barthélemy)", "Marigot (Saint-Martin)", "Cayenne (Guyane)",
        "Saint-Pierre (Saint-Pierre-et-Miquelon)", "Papeete (Polynésie française)",
    )]
    monkeypatch.setattr(voyage_store, "load_voyage", lambda _vid: {"marks": marks, "clock": {"marks": marks[2:]}})
    plan = {"chapters": [
        {"fromName": "Cayenne (Guyane)", "toName": "Halifax (Nouvelle-Écosse)"},
        {"fromName": "Halifax (Nouvelle-Écosse)", "toName": "Saint-Pierre (Saint-Pierre-et-Miquelon)"},
    ]}
    rows = fs._route_stops_for_reread(plan)
    names = [r.get("name") for r in rows]
    assert names.index("Halifax (Nouvelle-Écosse)") == names.index("Cayenne (Guyane)") + 1
    text = ("Le 23 août, à Saint-Pierre (Saint-Pierre-et-Miquelon), l'équipage reprend le second "
            "voilier pour Halifax (Nouvelle-Écosse). Arrivée à Halifax (Nouvelle-Écosse) le 28 août.")
    assert not fs._absent_places(text, rows)


def test_en_upcoming_stops_sentence_is_not_an_invented_name():
    """« Upcoming stops: … » (fin de l'intégral au now réel) ne retombe pas en français."""
    src = ("Aujourd'hui, le bateau est à Mata-Utu (Wallis-et-Futuna). "
           "Les escales à venir : Nouméa, Dzaoudzi, Tromelin, Saint-Gilles, Europa, La Rochelle.")
    en = ("Today, the boat is at Mata-Utu (Wallis and Futuna). "
          "Upcoming stops: Nouméa, Dzaoudzi, Tromelin, Saint-Gilles, Europa, La Rochelle.")
    facts = {"places": ["Mata-Utu (Wallis-et-Futuna)", "Nouméa", "Dzaoudzi", "Tromelin",
                        "Saint-Gilles", "Europa", "La Rochelle"],
             "en_names": sorted(n.title() for n in fs._en_translation_names(en, src))}
    guarded, rewritten, fallen = fs.apply_written_guard(src, en, facts, lang="en")
    assert fallen == 0 and rewritten == 2
    assert "escales à venir" not in guarded
