"""Lot fix/film-restants-2 (29/10/2026) : défauts restants du film rédigé, chacun reproduit.

(a) la 2:30 perdait tous ses sujets (aire marine, projet corail) à la condensation ;
(a') « Le lendemain » orphelin au 2:30 (Pointe d'Arçay dite le 25 février, vue le 30 mai) ;
(b) film arrêté au « now » réel : « pour la dernière étape » sur Papeete → Mata-Utu ;
(c) chapitres du second voilier : « reprend un second voilier », bilan non replié,
    « le vent tourne à l'ouest » puis « les vents d'ouest s'installent » ;
(d) apostrophes mêlées « l'équipage s'envole d’Halifax ».
"""
import json
import re
from pathlib import Path

import film_script as fs

FIX = Path(__file__).parent / "fixtures" / "film_150_raw_2026-10-29.json"


def _condensed_150():
    raw = json.loads(FIX.read_text(encoding="utf-8"))
    plan = fs._plan_digits_for_speech(raw, raw)
    return fs.condense_written_plan(plan, 150, lang="fr")


def _blob(plan):
    return " ".join(c.get("text") or "" for c in plan["chapters"])


def test_a_condensed_150_keeps_one_amp_and_the_coral_project():
    out = _condensed_150()
    blob = _blob(out)
    assert re.search(r"aire marine protégée Pointe d['’]Arçay", blob), blob
    assert re.search(r"le projet Restaurer les coraux", blob), blob
    # Toujours sous le plafond dur de 2:30.
    assert out["chars"] <= fs.film_char_budget(150) - int(fs.FILM_ESTIMATE_CPS), out["chars"]
    assert out["estimatedSeconds"] <= 150


def test_a_condensed_150_never_orphans_le_lendemain():
    out = _condensed_150()
    last = out["chapters"][-1]["text"]
    assert "Le lendemain, le bateau passe près" not in last, last
    assert "Puis, le bateau passe près de l'aire marine protégée Pointe d'Arçay" in last, last


def test_a_subjects_drop_last_when_no_room():
    # Pas de place du tout : les sujets partent, la distance et les escales restent.
    chapters = [{
        "id": "a", "fromName": "Europa (TAAF)", "toName": "La Rochelle",
        "text": "Le 24 février, départ vers La Rochelle : 8 393 milles, 96 jours. "
                "Puis, le bateau passe près de l'aire marine protégée Pointe d'Arçay, à 3 milles. "
                "Arrivée à La Rochelle le 31 mai.",
    }]
    keys = fs._condense_subject_keys(chapters)
    assert keys and keys[0].startswith("pointe d")
    assert fs._condensable_sentence(chapters[0], fs._sentences(chapters[0]["text"]), keys) == -1


def test_b_chapter_shape_last_follows_window_flag_not_index():
    w = {"last": False, "vehicle": "main", "mode": "sail"}
    assert fs.chapter_shape(w, 11, 12, {"daysAtSea": 9.0, "legNm": 1642}) != "last"
    assert fs.chapter_shape({**w, "last": True}, 11, 12, {"daysAtSea": 9.0}) == "last"
    # Fenêtre sans drapeau (appel direct) : l'index sert encore à défaut.
    assert fs.chapter_shape({"vehicle": "main"}, 11, 12, {"daysAtSea": 9.0}) == "last"


def test_c_return_leg_takes_the_same_second_boat():
    w = {"fromName": "Saint-Pierre (Saint-Pierre-et-Miquelon)", "destName": "Halifax (Nouvelle-Écosse)",
         "toName": "Halifax (Nouvelle-Écosse)", "arrived": True, "tA": 0, "tB": 1}
    fr = fs._side_opening_sentence(w, lang="fr")
    assert "reprend le second voilier pour Halifax" in fr, fr
    en = fs._side_opening_sentence(w, lang="en")
    assert "sails again on the second sailing boat" in en, en
    out = {**w, "fromName": "Halifax (Nouvelle-Écosse)", "destName": "Saint-Pierre (Saint-Pierre-et-Miquelon)"}
    assert "embarque sur un second voilier" in fs._side_opening_sentence(out, lang="fr")


def test_c_second_boat_stats_fold_like_every_leg():
    t = ("Le 19 août, à Halifax, l'équipage embarque sur un second voilier pour Saint-Pierre "
         "(Saint-Pierre-et-Miquelon). 497 milles, trois jours de mer. Arrivée à Saint-Pierre le 21 août.")
    assert "second voilier pour Saint-Pierre (Saint-Pierre-et-Miquelon) : 497 milles, trois jours de mer." in fs._fold_leg_stats(t)
    e = ("On 19 August, in Halifax, the crew boards a second sailing boat for Saint-Pierre. "
         "497 miles, three days at sea. Arrival in Saint-Pierre on 21 August.")
    assert "second sailing boat for Saint-Pierre: 497 miles, three days at sea." in fs._fold_leg_stats(e)


def test_c_wind_turn_then_same_belt_said_once():
    sents = [
        "Le 19 août, à Halifax, l'équipage embarque sur un second voilier pour Saint-Pierre.",
        "497 milles, trois jours de mer.",
        "Puis, le vent tourne à l'ouest : 8 nœuds, la moyenne de saison.",
        "Puis, les vents d'ouest s'installent : 12 nœuds, la moyenne de saison.",
        "Arrivée à Saint-Pierre le 21 août.",
    ]
    out = fs.thin_chapter_dates(sents, "fr")
    assert not any("tourne à l'ouest" in s for s in out), out
    assert any("vents d'ouest s'installent" in s for s in out), out
    # Une autre direction reste : ce n'est pas une redite.
    other = fs.drop_turn_before_same_belt([
        "Le lendemain, le vent tourne au nord-est : 6 nœuds.",
        "Puis, à l'équateur, les alizés de sud-est s'installent : 12 nœuds.",
    ])
    assert len(other) == 2
    en = fs.drop_turn_before_same_belt([
        "Then, the wind shifts to the northeast: 6 knots.",
        "On 30 August, the northeasterly trade winds set in: 12 knots.",
    ])
    assert len(en) == 1 and "trade winds" in en[0]


def test_d_one_apostrophe_in_the_whole_written_film():
    plan = {"chapters": [
        {"id": "a", "text": "L’expédition a quitté Saint-Maur par la route jusqu’à La Rochelle. 3 jours d'escale."},
        {"id": "b", "text": "Le 28 août, l'équipage s'envole de Halifax pour Cayenne, à l'ouest."},
    ]}
    out = fs._polish_written_plan(plan, plan, "fr")
    blob = _blob(out)
    assert "s'envole d'Halifax" in blob, blob
    assert "’" not in blob, blob
    assert "L'expédition" in blob and "jusqu'à" in blob


def test_d_raw_air_back_sentence_single_apostrophe():
    w = {"fromName": "Halifax (Nouvelle-Écosse)", "destName": "Cayenne (Guyane)", "toName": "Cayenne (Guyane)",
         "vehicle": "plane", "mode": "air", "arrived": True, "tA": 1787875200000, "tB": 1787961600000}
    s = fs._air_window_sentence(w, lang="fr")
    assert s == "Le 28 août, l'équipage s'envole d'Halifax pour Cayenne.", s
