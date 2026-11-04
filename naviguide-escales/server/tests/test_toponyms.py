"""Table de toponymes sourcée, homonymes distingués, casse d'origine."""
from __future__ import annotations

from toponyms import (
    consecutive_homonyms,
    group_waters,
    lookup,
    origin_name,
    sheet_label,
    sources,
    territories,
    waters_label,
)


def test_table_is_sourced_and_covers_the_official_route():
    assert len(sources()) >= 2
    assert any("1993" in s or "UNTERM" in s for s in sources())
    assert any("Marine Regions" in s for s in sources())
    ids = {row["id"] for row in territories()}
    for needed in ("es", "fr", "kn", "bq_eustatius", "sx", "mf", "ht", "do", "tl", "pg"):
        assert needed in ids, needed
    assert len(territories()) >= 60


def test_exonyms_fr_en_not_machine_translated():
    assert waters_label("Spanish Exclusive Economic Zone", "fr") == "les eaux espagnoles"
    assert waters_label("Spanish Exclusive Economic Zone", "en") == "Spanish waters"
    assert "Saint-Christophe-et-Niévès" in waters_label(
        "Kittitian and Nevisian Exclusive Economic Zone", "fr",
    )
    assert "Saint Kitts and Nevis" in waters_label(
        "Kittitian and Nevisian Exclusive Economic Zone", "en",
    )
    assert "Saint-Eustache" in waters_label("Sint-Eustatius Exclusive Economic Zone", "fr")
    assert "Sint Eustatius" in waters_label("Sint-Eustatius Exclusive Economic Zone", "en")


def test_shared_island_saint_martin_sint_maarten():
    mf = lookup("Saint-Martin Exclusive Economic Zone")
    sx = lookup("Sint-Maarten Exclusive Economic Zone")
    assert mf and sx and mf["id"] != sx["id"]
    assert mf["iso"] == "MF" and sx["iso"] == "SX"
    assert mf["island"] == sx["island"] == "saint_martin"
    fr = group_waters([
        "Sint-Maarten Exclusive Economic Zone",
        "Saint-Martin Exclusive Economic Zone",
    ], "fr")
    assert "Sint Maarten (partie néerlandaise)" in fr
    assert "Saint-Martin (partie française)" in fr
    assert consecutive_homonyms(fr) == []
    en = group_waters([
        "Sint-Maarten Exclusive Economic Zone",
        "Saint-Martin Exclusive Economic Zone",
    ], "en")
    assert "Sint Maarten (Dutch side)" in en
    assert "Saint-Martin (French side)" in en
    assert consecutive_homonyms(en) == []
    assert consecutive_homonyms("les eaux de Saint-Martin, puis celles de Saint-Martin")


def test_sheet_guadeloupe_keeps_existing_gabarit():
    assert sheet_label(
        "French Exclusive Economic Zone (Guadeloupe)", "fr", mrgid=33177, territory="guadeloupe",
    ) == "Zone économique exclusive française (Guadeloupe)"
    assert sheet_label(
        "French Exclusive Economic Zone (Guadeloupe)", "en", mrgid=33177, territory="guadeloupe",
    ) == "French EEZ (Guadeloupe)"


def test_origin_name_title_cases_all_caps_keeps_mixed():
    assert origin_name("LA ROCHELLE") == "La Rochelle"
    assert origin_name("MUXIA") == "Muxía"
    assert origin_name("LA CORUNA") == "La Coruña"
    assert origin_name("Porto Torres") == "Porto Torres"
    assert origin_name("Cabo Verde Marine Protected Areas Network") == (
        "Cabo Verde Marine Protected Areas Network"
    )


def test_hispaniola_and_timor_are_annotated():
    ht = lookup("Haitian Exclusive Economic Zone")
    do = lookup("Dominican Republic Exclusive Economic Zone")
    assert ht["island"] == do["island"] == "hispaniola"
    assert ht["id"] != do["id"]
    tl = lookup("Timor-Leste Exclusive Economic Zone")
    assert tl and tl["island"] == "timor"
    pg = lookup("Papua New Guinea Exclusive Economic Zone")
    assert pg and pg["island"] == "new_guinea"


def test_indian_ocean_waters_have_french_exonyms():
    """Film 29/10 00 h 46 : « les eaux Sri Lankan », « les eaux Maldivian » (démonyme anglais brut)."""
    assert waters_label("Sri Lankan Exclusive Economic Zone", "fr") == "les eaux sri-lankaises"
    assert waters_label("Maldivian Exclusive Economic Zone", "fr") == "les eaux maldiviennes"
    assert waters_label("Maldives Exclusive Economic Zone", "fr") == "les eaux maldiviennes"
    assert waters_label("Sri Lankan Exclusive Economic Zone", "en") == "Sri Lankan waters"
    assert waters_label("Omani Exclusive Economic Zone", "fr") == "les eaux omanaises"
    # « \boman » ne capture pas Romanian ; l'Inde reste l'Inde.
    assert lookup("Romanian Exclusive Economic Zone") is None or lookup("Romanian Exclusive Economic Zone")["id"] != "om"
    assert waters_label("Indian Exclusive Economic Zone", "fr") == "les eaux indiennes"


def test_no_english_demonym_left_on_common_eez_names():
    import re as _re
    names = [
        "Sri Lankan", "Maldivian", "Somali", "Omani", "Yemeni", "Djiboutian", "Pakistani",
        "Myanmar", "Thailand", "Malaysian", "Singaporean", "Nauruan", "Marshallese",
        "Micronesian", "Palauan", "Namibian", "Angolan", "Gambian",
    ]
    for n in names:
        fr = waters_label(f"{n} Exclusive Economic Zone", "fr")
        assert fr.startswith("les eaux ") and not _re.search(r"[A-Z]", fr[len("les eaux "):]), (n, fr)


def test_gambia_alias_does_not_capture_gambier_islands():
    """Contre-revue 136-137 P2-6 : « Gambier Islands » (Polynésie) n'est pas la Gambie."""
    hit = lookup("Gambier Islands")
    assert hit is None or hit["id"] != "gm"
    assert "gambiennes" not in waters_label("Gambier Islands", "fr")
    assert lookup("Gambia")["id"] == "gm"
    assert lookup("Gambian Exclusive Economic Zone")["id"] == "gm"
    assert waters_label("Gambian Exclusive Economic Zone", "fr") == "les eaux gambiennes"
