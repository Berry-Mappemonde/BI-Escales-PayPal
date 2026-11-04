"""Restants du film rédigé relevés à 03 h 14 le 29/10/2026 (lot fix/film-restants-0350).

Chaque test échoue sans le correctif : 2:30 estimé à ~158 s, distance Cayenne → Papeete
perdue à la condensation, « s'envole de Halifax », chiffres et lettres mêlés.
"""
import copy
import json
import pathlib
import re

import film_script as fs

FIX = pathlib.Path(__file__).parent / "fixtures" / "film_integral_written_2026-10-29.json"


def _integral(lang):
    return copy.deepcopy(json.loads(FIX.read_text(encoding="utf-8"))[lang])


def test_150_from_real_integral_fits_150_seconds_fr_and_en():
    for lang in ("fr", "en"):
        plan = fs.condense_written_plan(_integral(lang), 150, lang=lang)
        assert plan["estimatedSeconds"] <= 150, (lang, plan["chars"], plan["estimatedSeconds"])
        assert plan["chars"] <= fs.film_char_budget(150), (lang, plan["chars"])


def test_150_keeps_every_leg_distance_including_cayenne_papeete():
    full = _integral("fr")
    plan = fs.condense_written_plan(full, 150, lang="fr")
    blob = " ".join(c["text"] for c in plan["chapters"])
    papeete = next(c["text"] for c in plan["chapters"] if "départ vers Papeete" in c["text"])
    assert "6 671 milles" in papeete, papeete
    # Toutes les distances d'étape de l'intégral sont encore dites au 2:30.
    legs = re.findall(r"(\d[\d ]*\d) milles, [^.]*?jours? de mer", " ".join(c["text"] for c in full["chapters"]))
    for nm in legs:
        assert f"{nm} milles" in blob, nm
    en = fs.condense_written_plan(_integral("en"), 150, lang="en")
    en_papeete = next(c["text"] for c in en["chapters"] if "Papeete (" in c["text"] and "departure" in c["text"])
    assert "6,671 miles" in en_papeete, en_papeete


def test_leg_stats_sentence_never_condensed_and_folded():
    ch = {
        "id": "c1", "fromName": "Cayenne (Guyane)", "toName": "Papeete (Polynésie française)",
        "text": (
            "Le 29 août, le catamaran reprend la mer, départ vers Papeete (Polynésie française). "
            "6 671 milles, 46 jours de mer, à 6 nœuds de moyenne. "
            "Puis, les alizés de sud-est s'installent : douze nœuds, la moyenne de saison. "
            "Arrivée à Papeete (Polynésie française) le 14 octobre."
        ),
    }
    chapters = [ch]
    fs._condense_to_spoken_seconds(chapters, 8)
    text = chapters[0]["text"]
    assert re.search(r"départ vers Papeete(?: \(Polynésie française\))? : 6 671 milles, 46 jours", text), text
    assert "Arrivée à Papeete" in text and "14 octobre" in text


def test_regions_said_once_across_the_film():
    chapters = [
        {"id": "a", "text": "Le 18 août, l'équipage s'envole de Cayenne (Guyane) pour Halifax (Nouvelle-Écosse) ; le catamaran attend à Cayenne (Guyane)."},
        {"id": "b", "text": "Le 19 août, à Halifax, en Nouvelle-Écosse, l'équipage embarque pour Saint-Pierre, à Saint-Pierre-et-Miquelon. Arrivée à Saint-Pierre, à Saint-Pierre-et-Miquelon, le 21 août."},
    ]
    fs._drop_repeated_regions(chapters)
    assert chapters[0]["text"].count("(Guyane)") == 1
    assert "(Nouvelle-Écosse)" in chapters[0]["text"]
    assert "en Nouvelle-Écosse" not in chapters[1]["text"]
    assert "Arrivée à Saint-Pierre le 21 août." in chapters[1]["text"], chapters[1]["text"]


def test_air_back_sentence_elides_halifax_and_both_regexes_match():
    assert fs._de("Halifax") == "d’Halifax"
    s = "Le 28 août, l'équipage s'envole d’Halifax pour Cayenne."
    assert fs._AIR_BACK_RE.search(s)
    assert fs._AIR_BACK_RE.search("Le 28 août, l’équipage s’envole de Halifax pour Cayenne.")
    assert not fs._AIR_OUT_RE.search(s)
    # Lot film-restants-2 : l'apostrophe suit celle du texte (plus « s'envole d’Halifax »).
    assert fs.fr_elide_de("l'équipage s'envole de Halifax pour Cayenne") == "l'équipage s'envole d'Halifax pour Cayenne"
    assert fs.fr_elide_de("l’équipage s’envole de Halifax pour Cayenne") == "l’équipage s’envole d’Halifax pour Cayenne"
    # Sigles et consonnes : inchangés.
    assert fs.fr_elide_de("de TAAF, de Papeete") == "de TAAF, de Papeete"


def test_unit_numbers_one_spelling():
    src = "Puis, à vingt-sept milles, le projet X. Le 28 juin, à 28 milles. Les alizés : douze nœuds, puis 14 nœuds, neuf nœuds."
    out = fs.unit_numbers_to_digits(src)
    assert out == "Puis, à 27 milles, le projet X. Le 28 juin, à 28 milles. Les alizés : 12 nœuds, puis 14 nœuds, 9 nœuds."
    # Approximations, jours et singuliers : inchangés.
    keep = "Une vingtaine de jours de mer, trois jours d'escale, un mille, one mile."
    assert fs.unit_numbers_to_digits(keep) == keep
    assert fs.unit_numbers_to_digits("at twenty-six miles, twelve knots") == "at 26 miles, 12 knots"


def test_en_le_month_fixed():
    assert fs.en_le_month("Le August 29, the catamaran puts to sea.") == "On August 29, the catamaran puts to sea."
    assert fs.en_le_month("Le Marin") == "Le Marin"


def test_stamp_recomputes_estimated_seconds():
    plan = {"chapters": [{"id": "a", "text": "x" * 300}], "estimatedSeconds": 158}
    out = fs._stamp_written_plan(plan, fs.WRITTEN_SOURCE, 150)
    assert out["estimatedSeconds"] == 20


def test_polish_written_plan_fr_and_en():
    raw = {"chapters": [{"id": "a", "text": "Le 28 août, l'équipage s'envole d’Halifax pour Cayenne. Puis, à vingt-sept milles."}]}
    fr = fs._polish_written_plan(
        {"chapters": [{"id": "a", "text": "Le 28 août, l'équipage s'envole de Halifax pour Cayenne. Puis, à vingt-sept milles."}]},
        raw, "fr",
    )
    assert fr["chapters"][0]["text"] == "Le 28 août, l'équipage s'envole d'Halifax pour Cayenne. Puis, à 27 milles."
    en = fs._polish_written_plan(
        {"chapters": [{"id": "a", "text": "Le August 28, the crew flies from Halifax. Then, at twenty-seven miles."}]},
        raw, "en",
    )
    assert en["chapters"][0]["text"] == "On August 28, the crew flies from Halifax. Then, at 27 miles."


def test_inline_region_repeated_word_for_word_said_once():
    chapters = [{"id": "a", "text": (
        "Le 29 août, départ vers Papeete en Polynésie française : 6 671 milles, 46 jours. "
        "Arrivée à Papeete en Polynésie française le 14 octobre."
    )}, {"id": "b", "text": (
        "On August 29, heading to Papeete in French Polynesia: 6,671 miles. "
        "Arrival in Papeete in French Polynesia on October 14. Arrival in Halifax in August."
    )}]
    fs._drop_repeated_regions(chapters)
    assert chapters[0]["text"].endswith("Arrivée à Papeete le 14 octobre."), chapters[0]["text"]
    assert "Arrival in Papeete on October 14." in chapters[1]["text"], chapters[1]["text"]
    assert "Halifax in August" in chapters[1]["text"]


def test_one_day_at_sea_kept_whole():
    chapters = [{"id": f"c{i}", "fromName": "A", "toName": "B", "text": (
        "Le 17 juillet, départ vers Pointe-à-Pitre : 192 milles, un jour de mer. "
        "Le 30 juillet, départ vers Cayenne : 1 200 milles, une quinzaine de jours de mer. "
        "Arrivée à Cayenne le 15 août."
    )} for i in range(16)]
    fs._condense_to_spoken_seconds(chapters, 150)
    t = chapters[0]["text"]
    assert "un jour de mer" in t, t
    assert "une quinzaine de jours." in t, t

