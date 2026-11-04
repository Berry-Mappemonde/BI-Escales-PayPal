"""Garde de traduction EN du film (VERIF-FILM-0515 N1-N9) : déterministe après Lightning.

Chaque cas reprend un paragraphe réel des films du 29/10/2026 04 h 45 : le français
accepté, et l'anglais fautif que Lightning a rendu.
"""
import asyncio

import film_script as fs


def _translate(fr_text: str, en_text: str) -> str:
    raw_ch = {"id": "c1", "text": fr_text, "anchors": []}

    async def tr(system, user, **kw):
        return en_text, "nemotron-lightning"

    en = asyncio.run(fs.translate_written_plan({"chapters": [raw_ch]}, {"chapters": [raw_ch]}, cascade=tr))
    assert en, "la traduction ne doit pas tomber"
    return en["chapters"][0]["text"]


# --- N1 : date française laissée dans l'anglais ---------------------------------------

FR_N1 = ("Le 29 août, le catamaran reprend la mer, départ vers Papeete (Polynésie française). "
         "6 671 milles, 46 jours de mer.")
EN_N1 = ("Le 29 août, the catamaran resumes the sea, departure for Papeete (French Polynesia). "
         "6,671 miles, 46 days at sea.")


def test_n1_no_french_date_in_english_film():
    out = _translate(FR_N1, EN_N1)
    assert "août" not in out and not out.startswith("Le ")
    assert out.startswith("On August 29, the catamaran")


def test_n1_french_date_helper_forms():
    assert fs.en_french_dates("Le 1er juin, departure.") == "On June 1, departure."
    assert fs.en_french_dates("Arrival le 14 octobre 2026.") == "Arrival on October 14, 2026."
    assert fs.en_french_dates("Then, 3 janvier, high seas.") == "Then, January 3, high seas."
    assert fs.en_french_dates("On August 29, departure.") == "On August 29, departure."


# --- N2 : glissement de durée -----------------------------------------------------------

FR_N2 = ("L'expédition Berry-Mappemonde a quitté Saint-Maur le 15 mai 2026 par la route jusqu'à La Rochelle. "
         "Le jour même, départ vers Ajaccio : 1 819 milles, une vingtaine de jours. Arrivée à Ajaccio le 1er juin.")
EN_N2 = ("The Berry-Mappemonde expedition left Saint-Maur on May 15, 2026 by road to La Rochelle. "
         "On the same day, departure to Ajaccio: 1,819 miles, a couple of weeks. Arrival in Ajaccio on June 1.")


def test_n2_vingtaine_is_about_twenty_days():
    out = _translate(FR_N2, EN_N2)
    assert "couple of weeks" not in out
    assert "1,819 miles, about twenty days." in out


def test_n2_approx_helper():
    fr = "Départ : 925 milles, une vingtaine de jours."
    for drift in ("a couple of weeks", "about three weeks", "a fortnight", "some fifteen days",
                  "about 25 days", "nearly a month"):
        assert fs.fix_en_approx_days(f"Departure: 925 miles, {drift}.", fr) == \
            "Departure: 925 miles, about twenty days."
    # Déjà juste, ou approximation sans équivalent fixé (quinzaine) : on ne touche pas.
    assert fs.fix_en_approx_days("925 miles, about twenty days.", fr) == "925 miles, about twenty days."
    assert fs.fix_en_approx_days("1,200 miles, two weeks.", "1 200 milles, une quinzaine.") == \
        "1,200 miles, two weeks."
    # Durée exacte voisine : jamais réécrite.
    fr2 = "Départ : 6 671 milles, 46 jours de mer. Puis 925 milles, une vingtaine de jours."
    en2 = "Departure: 6,671 miles, 46 days at sea. Then 925 miles, a couple of weeks."
    assert fs.fix_en_approx_days(en2, fr2) == \
        "Departure: 6,671 miles, 46 days at sea. Then 925 miles, about twenty days."


# --- N3 à N9 : toponymie et tournures ---------------------------------------------------

FR_N3 = ("Le 30 juillet, Berry-Mappemonde quitte Marigot (Saint-Martin), cap au sud pour la longue traversée "
         "vers Cayenne (Guyane). Puis, les eaux de Saint-Eustache, puis celles de Saint-Christophe-et-Niévès, "
         "puis celles d'Antigua-et-Barbuda, puis les eaux grenadiennes, puis celles du Guyana. "
         "Le 14 août, les eaux de la Guyane. Arrivée à Cayenne (Guyane) le 15 août.")
EN_N3 = ("On July 30, Berry-Mappemonde departs Marigot (Saint-Martin), heading south for the long crossing "
         "to Cayenne (French Guiana). Then, the waters of Saint-Eustache, then those of Saint-Christophe-et-Niévès, "
         "then those of Antigua-et-Barbuda, then the Grenadine waters, then those of Guyana. "
         "On August 14, Guyanese waters. Arrival in Cayenne (French Guiana) on August 15.")


def test_n3_n4_n6_english_names_and_french_guiana():
    out = _translate(FR_N3, EN_N3)
    assert "the waters of Sint Eustatius" in out
    assert "those of Saint Kitts and Nevis" in out
    assert "those of Antigua and Barbuda" in out
    assert "Grenadian waters" in out
    assert "those of Guyana" in out  # le Guyana reste le Guyana
    assert "Guyanese waters" not in out and "On August 14, French Guiana waters." in out
    assert "Marigot (Saint-Martin)" in out  # les noms d'escale ne bougent pas


def test_n4_guyanese_kept_when_french_says_guyana():
    fr = "Puis, les eaux du Guyana."
    assert fs.fix_en_toponyms("Then, Guyanese waters.", fr) == "Then, Guyanese waters."


FR_N5 = "Le 4 décembre, les eaux indiennes. Puis, haute mer. Puis, les eaux sri-lankaises."
EN_N5 = "On December 4, Indian Ocean waters. Then, high seas. Then, Sri Lankan waters."


def test_n5_indian_waters_are_india_not_the_ocean():
    out = _translate(FR_N5, EN_N5)
    assert "Indian Ocean waters" not in out and "On December 4, Indian waters." in out


def test_n5_ocean_kept_when_french_says_ocean():
    fr = "Le 4 décembre, l'océan Indien."
    assert fs.fix_en_toponyms("On December 4, the Indian Ocean waters.", fr) == \
        "On December 4, the Indian Ocean waters."


def test_n6_saint_eustache_spaced():
    assert fs.fix_en_toponyms("then those of Saint Eustache, then", "puis celles de Saint-Eustache, puis") == \
        "then those of Sint Eustatius, then"


def test_n7_one_mile_word():
    assert fs.fix_en_toponyms("192 nautical miles, one day at sea. At 21 nautical miles, the project.", "") == \
        "192 miles, one day at sea. At 21 miles, the project."


def test_n9_second_vessel_is_boarded_again():
    fr = "Le 23 août, à Saint-Pierre, l'équipage reprend le second voilier pour Halifax."
    en = "On August 23, at Saint-Pierre, the crew takes over the second vessel for Halifax."
    assert fs.fix_en_toponyms(en, fr) == \
        "On August 23, at Saint-Pierre, the crew boards the second vessel again for Halifax."


def test_guard_is_idempotent():
    once = fs.fix_en_toponyms(EN_N3, FR_N3)
    assert fs.fix_en_toponyms(once, FR_N3) == once
    a = fs.fix_en_approx_days(EN_N2, FR_N2)
    assert fs.fix_en_approx_days(a, FR_N2) == a


def test_n4_bis_cayenne_in_french_guiana_not_guyana():
    fr = "Marigot (Saint-Martin), cap au sud pour la longue traversée vers Cayenne (Guyane)."
    en = "Marigot (Saint-Martin), heading south for the long crossing to Cayenne (Guyana)."
    assert fs.fix_en_toponyms(en, fr) == \
        "Marigot (Saint-Martin), heading south for the long crossing to Cayenne (French Guiana)."
    # Le Guyana (Georgetown) reste le Guyana.
    assert fs.fix_en_toponyms("Georgetown (Guyana).", "Georgetown (Guyana).") == "Georgetown (Guyana)."
