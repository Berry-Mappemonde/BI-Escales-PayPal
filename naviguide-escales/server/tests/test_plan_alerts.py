"""Evaluate_plan : contrat § 3.1, cyclone daté, cache, hors ligne."""
from __future__ import annotations

import copy
import time

from moment import load_official_mini
from plan_alerts import (
    _fmt,
    cache_info,
    clear_plan_cache,
    evaluate_plan,
    load_climatology_mini,
    plan_from_voyage,
    sample_track,
)


def test_alert_decimal_format_respects_english_and_french():
    assert _fmt(2.7, 1, "en") == "2.7"
    assert _fmt(2.7, 1, "fr") == "2,7"

NOW = "2026-09-22T12:00:00Z"
TH = {"galeKt": 34, "hsAlertM": 3.0}

NOUMEA_POINTS = [
    {"lat": -22.27, "lon": 166.45},
    {"lat": -21.9, "lon": 165.4},
    {"lat": -21.6, "lon": 164.4},
]


def setup_function():
    clear_plan_cache()


def _noumea_leg(depart: str) -> dict:
    return {
        "from": "Nouméa",
        "to": "Dzaoudzi",
        "depart": depart,
        "kn": 8.0,
        "holdDays": 3,
        "points": copy.deepcopy(NOUMEA_POINTS),
    }


def _noumea_plan(depart: str) -> dict:
    return {"legs": [_noumea_leg(depart)], "skipper_thresholds": TH}


def _kinds(result: dict) -> set[str]:
    return {a["kind"] for leg in result["legs"] for a in leg["alerts"]}


def test_climatology_mini_is_twelve_months_by_six_cells():
    blob = load_climatology_mini()
    cells = blob["cells"]
    assert len(cells) == 6
    for cell in cells:
        assert len(cell["wind_p90_kn"]) == 12
        assert len(cell["hs_p90_m"]) == 12
    named = {c["id"]: c for c in cells}
    assert named["noumea"]["cyclones"][0]["date"] == "10-15"
    assert named["swio"]["cyclones"][0]["date"] == "01-13"


def test_official_voyage_evaluates_under_two_seconds():
    voy = load_official_mini()
    started = time.perf_counter()
    out = evaluate_plan(voy, now=NOW)
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0, elapsed
    assert len(out["legs"]) == 2
    assert out["legs"][0]["from"] == "La Rochelle"
    assert out["legs"][0]["to"] == "Fort-de-France (Martinique)"
    assert out["legs"][1]["to"] == "Pointe-à-Pitre (Guadeloupe)"
    assert out["total"] == sum(leg["score"] for leg in out["legs"])
    assert all(leg["frozen"] for leg in out["legs"]), "les deux jambes du mini sont déjà naviguées au 22 sept."


def test_shifting_noumea_plus_30_days_changes_the_total():
    oct1 = evaluate_plan(_noumea_plan("2026-10-01"), now=NOW)
    oct31 = evaluate_plan(_noumea_plan("2026-10-31"), now=NOW)
    assert oct1["total"] != oct31["total"]
    assert "cyclone" in _kinds(oct1)
    assert "cyclone" not in _kinds(oct31)


def test_past_legs_never_change():
    voy = load_official_mini()
    base = plan_from_voyage(voy, now=NOW)
    early = copy.deepcopy(base)
    early["legs"].append(_noumea_leg("2026-10-01"))
    late = copy.deepcopy(base)
    late["legs"].append(_noumea_leg("2026-10-31"))
    a = evaluate_plan(early, now=NOW)
    b = evaluate_plan(late, now=NOW)
    frozen_a = [leg for leg in a["legs"] if leg["frozen"]]
    frozen_b = [leg for leg in b["legs"] if leg["frozen"]]
    assert frozen_a, "La Rochelle et Fort-de-France sont passées"
    assert len(frozen_a) == len(frozen_b)
    for left, right in zip(frozen_a, frozen_b):
        assert left["from"] == right["from"] and left["to"] == right["to"]
        assert left["alerts"] == right["alerts"]
        assert left["score"] == right["score"]
    future = [leg for leg in a["legs"] if not leg["frozen"]]
    assert future and future[0]["from"] == "Nouméa"
    assert a["total"] != b["total"]


def test_every_alert_has_a_fact_and_a_when():
    voy = load_official_mini()
    official = evaluate_plan(voy, now=NOW)
    noumea = evaluate_plan(_noumea_plan("2026-10-01"), now=NOW)
    alerts = [a for leg in official["legs"] + noumea["legs"] for a in leg["alerts"]]
    assert alerts, "le plan Nouméa du 1er octobre doit produire au moins une alerte"
    for alert in alerts:
        assert alert["fact"] and str(alert["fact"]).strip()
        assert alert["when"] and len(str(alert["when"])) >= 10
        assert 1 <= int(alert["weight"]) <= 3
        assert alert["kind"]
        assert alert["severity"] in {"alert", "decision"}
        assert "lat" in (alert.get("where") or {}) and "lon" in alert["where"]


def test_cyclone_track_off_season_is_silent_on_date_it_alerts():
    silent = evaluate_plan(_noumea_plan("2026-07-15"), now=NOW)
    dated = evaluate_plan(_noumea_plan("2026-10-15"), now=NOW)
    assert "cyclone" not in _kinds(silent)
    cyclones = [a for leg in dated["legs"] for a in leg["alerts"] if a["kind"] == "cyclone"]
    assert cyclones
    assert any("Cook" in a["fact"] and "15/10" in a["fact"] for a in cyclones)
    assert all(a["when"] for a in cyclones)


def test_cache_hits_same_track_dates_thresholds():
    voy = load_official_mini()
    first = evaluate_plan(voy, now=NOW)
    info = cache_info()
    assert info["misses"] == 1 and info["hits"] == 0
    second = evaluate_plan(voy, now=NOW)
    assert second == first
    assert cache_info()["hits"] == 1
    evaluate_plan(voy, now=NOW)
    assert cache_info()["hits"] == 2


def test_sample_track_every_sixty_nm():
    points = [
        {"lat": 0.0, "lon": 0.0, "sailNm": 0},
        {"lat": 1.0, "lon": 0.0, "sailNm": 180},
    ]
    samples = sample_track(points)
    nms = [s["nm"] for s in samples]
    assert nms[0] == 0
    assert 60 in nms and 120 in nms
    assert nms[-1] == 180
