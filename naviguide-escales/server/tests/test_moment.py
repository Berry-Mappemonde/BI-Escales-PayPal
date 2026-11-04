"""Build_moment : contrat Moment, signature stable, noms localisés."""
from __future__ import annotations

import copy
import json

from moment import (
    build_moment,
    load_official_mini,
    localize_zee_name,
    signature,
)


def _fixture():
    return load_official_mini()


def _pearl_by_mrgid(voy, mrgid):
    for pearl in voy["pearls"]:
        if (pearl.get("zee") or {}).get("mrgid") == mrgid:
            return pearl
    raise AssertionError(f"no pearl with mrgid {mrgid}")


def _clock_near(voy, sail_nm):
    verts = voy["clock"]["vertices"]
    return min(verts, key=lambda v: abs(float(v.get("sailNm") or 0) - sail_nm))


def _inputs(voy=None, mrgid=33177, extra_pearl=None, extra_clock=None, extra_leg=None, lang="fr"):
    voy = voy or _fixture()
    pearl = copy.deepcopy(_pearl_by_mrgid(voy, mrgid))
    if extra_pearl:
        pearl.update(extra_pearl)
    clock = copy.deepcopy(_clock_near(voy, pearl["sailNm"]))
    if extra_clock:
        clock.update(extra_clock)
    leg = copy.deepcopy(voy["legs"][1] if mrgid == 33177 else voy["legs"][0])
    if extra_leg:
        leg.update(extra_leg)
    return pearl, clock, leg, copy.deepcopy(voy["skipper_thresholds"]), lang


def test_fixture_shape():
    voy = _fixture()
    assert len(voy["marks"]) == 3
    assert len(voy["points"]) == 40
    assert len(voy["pearls"]) == 12
    assert voy["clock"]["t0"].startswith("2026-05-15")
    assert len(voy["clock"]["vertices"]) == 40
    assert {m["name"] for m in voy["marks"]} == {
        "La Rochelle",
        "Fort-de-France (Martinique)",
        "Pointe-à-Pitre (Guadeloupe)",
    }


def test_same_inputs_same_signature():
    args = _inputs()
    a = build_moment(*args[:-1], lang=args[-1])
    b = build_moment(*args[:-1], lang=args[-1])
    assert a["signature"] == b["signature"] == signature(a)
    assert a["signature"] == signature(b)


def test_one_more_mile_keeps_signature():
    pearl, clock, leg, th, lang = _inputs()
    base = build_moment(pearl, clock, leg, th, lang=lang)
    plus = copy.deepcopy(leg)
    plus["remainingNm"] = float(leg["remainingNm"]) + 1
    plus["doneNm"] = float(leg["doneNm"]) + 1
    clock_plus = copy.deepcopy(clock)
    clock_plus["sailNm"] = float(clock["sailNm"]) + 1
    again = build_moment(pearl, clock_plus, plus, th, lang=lang)
    assert again["leg"]["remainingNm"] == leg["remainingNm"] + 1
    assert again["signature"] == base["signature"]


def test_new_zee_changes_signature():
    pearl, clock, leg, th, lang = _inputs()
    base = build_moment(pearl, clock, leg, th, lang=lang)
    other = copy.deepcopy(pearl)
    other["zee"] = {
        "name": "Spanish Exclusive Economic Zone",
        "mrgid": 5693,
        "territory": None,
        "gold": False,
    }
    other["poe"] = []
    changed = build_moment(other, clock, leg, th, lang=lang)
    assert changed["here"]["zee"]["mrgid"] == 5693
    assert changed["signature"] != base["signature"]


def test_every_alert_has_a_non_empty_fact():
    pearl, clock, leg, th, lang = _inputs(
        extra_pearl={
            "zee": {
                "name": "Somewhere Exclusive Economic Zone",
                "mrgid": 9999,
                "gold": False,
            },
            "poe": [],
            "amp": [{
                "name": "Grand Cul-de-Sac Marin",
                "nm": 4.0,
                "site_id": "fr-amp-gcsm",
                "iucn_cat": "II",
                "designation": "parc national",
            }],
            "climatology": {"month": 9, "cyclone": {"nearby": 2, "in_season": True}},
            "weather": {"wind": {"speedKnots": 36.5}, "wave": {"hs": 3.4}},
        },
        extra_clock={"iso": "2026-09-15T22:00:00Z", "month": 9, "windKnots": 36.5, "hs": 3.4, "lon": -61.5},
        extra_leg={"eta": {"p10": "2026-09-16T23:30:00Z", "p90": "2026-09-17T04:00:00Z"}},
    )
    moment = build_moment(pearl, clock, leg, th, lang=lang)
    kinds = {a["kind"] for a in moment["alerts"]}
    assert {"wind", "sea", "cyclone", "entry", "mpa", "night"} <= kinds
    for alert in moment["alerts"]:
        assert alert["fact"] and str(alert["fact"]).strip()
        assert "99" not in alert["fact"]


def test_moment_is_json_serializable():
    pearl, clock, leg, th, lang = _inputs()
    moment = build_moment(pearl, clock, leg, th, lang=lang)
    blob = json.dumps(moment, ensure_ascii=False)
    back = json.loads(blob)
    assert back["signature"] == moment["signature"]
    assert back["here"]["zee"]["mrgid"] == 33177


def test_localized_zee_names_on_fixture_no_double_parens():
    pearl, clock, leg, th, _ = _inputs(mrgid=33177)
    assert "Guadeloupe" in pearl["zee"]["name"]
    fr = build_moment(pearl, clock, leg, th, lang="fr")
    en = build_moment(pearl, clock, leg, th, lang="en")
    assert fr["here"]["zee"]["name"] == "Zone économique exclusive française (Guadeloupe)"
    assert en["here"]["zee"]["name"] == "French EEZ (Guadeloupe)"
    text_fr = " ".join(fr["here"]["sentences"])
    text_en = " ".join(en["here"]["sentences"])
    assert "Zone économique exclusive française (Guadeloupe)" in text_fr
    assert "French Exclusive Economic Zone" not in text_fr
    assert "(Guadeloupe) (Guadeloupe)" not in text_fr
    assert "French EEZ (Guadeloupe)" in text_en
    assert "(Guadeloupe) (Guadeloupe)" not in text_en
    assert fr["here"]["entry"]["ports"] == ["Pointe-à-Pitre"]
    assert any("Grand Cul-de-Sac Marin" in (a.get("name") or "") for a in fr["here"]["mpa"])
    assert localize_zee_name(pearl["zee"], "fr") == fr["here"]["zee"]["name"]


def test_around_facts_use_requested_language_and_decimal_separator():
    pearl, clock, leg, thresholds, _ = _inputs(extra_pearl={
        "science": {"nearby": [{"name": "Buoy A", "nm": 2.7}]},
    })
    fr = build_moment(pearl, clock, leg, thresholds, lang="fr")
    en = build_moment(pearl, clock, leg, thresholds, lang="en")
    assert any(item["fact"] == "Buoy A (2,7 nm)" for item in fr["around"])
    assert any(item["fact"] == "Buoy A (2.7 nm)" for item in en["around"])


def test_rc32_saint_martin_sheet_distinguished():
    name = localize_zee_name(
        {"name": "Saint-Martin Exclusive Economic Zone", "mrgid": 8495, "territory": "saint_martin"},
        "fr",
    )
    assert "Saint-Martin (partie française)" in name
    assert "(Saint-Martin) (Saint-Martin)" not in name
    en = localize_zee_name(
        {"name": "Sint-Maarten Exclusive Economic Zone", "mrgid": 8433},
        "en",
    )
    assert "Sint Maarten (Dutch side)" in en


def test_guadeloupe_sources_have_no_ok():
    """Bi=ok dans la perle ne doit pas apparaître comme libellé « ok »."""
    pearl, clock, leg, th, lang = _inputs(mrgid=33177)
    assert (pearl.get("sources") or {}).get("bi") == "ok"
    moment = build_moment(pearl, clock, leg, th, lang=lang)
    sources = moment["sources"]
    lowered = {str(s).strip().lower() for s in sources}
    assert "ok" not in lowered
    assert "error" not in lowered
    assert "pending" not in lowered
    assert "VLIZ" in sources
    assert "Blue Intelligence" in sources
    assert "Open-Meteo" in sources
    assert "CDSE" in sources
    assert "EMODnet" in sources
    assert "OpenStreetMap" in sources
    assert "Atlas BI" in sources


def test_no_invented_numbers_in_facts():
    pearl, clock, leg, th, lang = _inputs(
        extra_clock={"windKnots": 36.5, "hs": 3.4, "iso": "2026-09-15T12:00:00Z", "month": 9},
        extra_pearl={"weather": {"wind": {"speedKnots": 36.5}, "wave": {"hs": 3.4}}},
    )
    moment = build_moment(pearl, clock, leg, th, lang=lang)
    blob = json.dumps(moment, ensure_ascii=False)
    assert "36,5" in blob or "36.5" in blob
    assert "3,4" in blob or "3.4" in blob
    assert "99" not in blob
    wind = next(a for a in moment["alerts"] if a["kind"] == "wind")
    assert "36" in wind["fact"] and "34" in wind["fact"]
