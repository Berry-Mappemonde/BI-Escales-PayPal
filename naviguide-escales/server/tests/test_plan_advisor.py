"""Advise : dates, corridors bornés, cap +20 %, déterminisme."""
from __future__ import annotations

import copy
import json
import time
from datetime import date, datetime, timedelta, timezone

from story_cascade import _numbers, filter_numbers

from isochrone import distance_to_track_nm, skipper_nogo
from moment import load_official_mini
from plan_advisor import (
    CORRIDOR_MAX_NM,
    CORRIDORS,
    DISTANCE_CAP_RATIO,
    SHIFT_DAYS,
    WEIGHT_EXTRA_NM,
    WEIGHT_SHIFT_PER_DAY,
    advise,
    bounded_isochrone,
    clear_advice_jobs,
    corridor_track,
    request_advice,
    resolve_advice_leg,
    review_legs,
    score_of,
    shift_plan,
    track_nm,
)
from plan_alerts import clear_plan_cache, evaluate_plan
from voyage_clock import OFFICIAL_VOYAGE_ID

NOW = "2026-09-22T12:00:00Z"
TH = {"galeKt": 34, "hsAlertM": 3.0}

NOUMEA_POINTS = [
    {"lat": -22.27, "lon": 166.45},
    {"lat": -21.9, "lon": 165.4},
    {"lat": -21.6, "lon": 164.4},
]
DZAOUDZI_POINTS = [
    {"lat": -12.78, "lon": 45.26},
    {"lat": -13.0, "lon": 44.8},
    {"lat": -13.2, "lon": 44.4},
]
CAPE_POINTS = [
    {"lat": -33.92, "lon": 18.42},
    {"lat": -34.1, "lon": 18.0},
]
BISCAY_POINTS = [
    {"lat": 46.15, "lon": -1.16},
    {"lat": 45.8, "lon": -2.0},
]


def setup_function():
    clear_plan_cache()
    clear_advice_jobs()


def _leg(idx, frm, to, depart, arrive, hold, points):
    return {
        "idx": idx, "from": frm, "to": to,
        "depart": depart, "arrive": arrive,
        "departIso": f"{depart}T08:00:00Z",
        "arriveIso": f"{arrive}T08:00:00Z",
        "holdDays": hold, "kn": 8.0,
        "points": copy.deepcopy(points),
    }


def _noumea_chain():
    """Nouméa 1er oct. → Dzaoudzi (+5 j à quai) → Le Cap (+3 j)."""
    return {
        "legs": [
            _leg(0, "Nouméa", "Dzaoudzi", "2026-10-01", "2026-10-02", 5, NOUMEA_POINTS),
            _leg(1, "Dzaoudzi", "Le Cap", "2026-10-07", "2026-10-09", 3, DZAOUDZI_POINTS),
            _leg(2, "Le Cap", "Sainte-Hélène", "2026-10-12", "2026-10-13", 2, CAPE_POINTS),
        ],
        "skipper_thresholds": TH,
    }


def _official_with_leg3():
    """Deux jambes figées + une courte + Nouméa en idx 3, puis une suivante."""
    return {
        "voyageId": OFFICIAL_VOYAGE_ID,
        "t0": "2026-05-15T08:00:00Z",
        "official": True,
        "skipper_thresholds": TH,
        "legs": [
            _leg(0, "La Rochelle", "Fort-de-France (Martinique)", "2026-05-15", "2026-06-02", 3, BISCAY_POINTS),
            _leg(1, "Fort-de-France (Martinique)", "Pointe-à-Pitre (Guadeloupe)", "2026-06-05", "2026-06-07", 2, BISCAY_POINTS),
            _leg(2, "Pointe-à-Pitre (Guadeloupe)", "Portsmouth", "2026-06-09", "2026-06-11", 2, BISCAY_POINTS),
            _leg(3, "Nouméa", "Dzaoudzi", "2026-10-01", "2026-10-02", 5, NOUMEA_POINTS),
            _leg(4, "Dzaoudzi", "Le Cap", "2026-10-07", "2026-10-09", 3, DZAOUDZI_POINTS),
        ],
    }


def _hold_gap(plan, i):
    a = datetime.fromisoformat(plan["legs"][i]["arrive"]).replace(tzinfo=timezone.utc)
    b = datetime.fromisoformat(plan["legs"][i + 1]["depart"]).replace(tzinfo=timezone.utc)
    return (b.date() - a.date()).days


def test_weights_are_fixed_constants():
    assert SHIFT_DAYS == (-21, -14, -7, 0, 7, 14, 21)
    assert WEIGHT_SHIFT_PER_DAY == 0.3
    assert WEIGHT_EXTRA_NM == 0.02
    assert score_of(10, 7, 41) == 10 + 0.3 * 7 + 0.02 * 41


def test_best_score_is_at_most_current_plan():
    plan = _noumea_chain()
    out = advise(plan, 0, now=NOW)
    current = score_of(evaluate_plan(plan, now=NOW)["total"], 0, 0)
    assert out["best"]["score"] <= current
    assert out["weights"] == {"shiftPerDay": 0.3, "extraNm": 0.02}
    assert out["best"]["shiftDays"] in SHIFT_DAYS
    assert len(out["alternatives"]) <= 3
    assert all(a["score"] >= out["best"]["score"] for a in out["alternatives"])


def test_cascade_shifts_every_following_stop_by_the_same_days():
    plan = _noumea_chain()
    days = 7
    shifted = shift_plan(plan, 0, days)
    out = advise(plan, 0, now=NOW)
    # On vérifie la mécanique sur un décalage connu, pas seulement le meilleur.
    for i, (was, now) in enumerate(zip(plan["legs"], shifted["legs"])):
        assert now["holdDays"] == was["holdDays"]
        was_arr = date.fromisoformat(was["arrive"])
        now_arr = date.fromisoformat(now["arrive"])
        was_dep = date.fromisoformat(was["depart"])
        now_dep = date.fromisoformat(now["depart"])
        assert (now_arr - was_arr).days == days
        assert (now_dep - was_dep).days == days
    cascade = out["best"]["cascade"]
    assert [c["stop"] for c in cascade] == ["Dzaoudzi", "Le Cap", "Sainte-Hélène"]
    shift = out["best"]["shiftDays"]
    for row, was in zip(cascade, plan["legs"]):
        assert date.fromisoformat(row["now"]) - date.fromisoformat(row["was"]) == timedelta(days=shift)


def test_days_at_dock_are_preserved():
    plan = _noumea_chain()
    assert _hold_gap(plan, 0) == 5
    assert _hold_gap(plan, 1) == 3
    for days in SHIFT_DAYS:
        shifted = shift_plan(plan, 0, days)
        assert [lg["holdDays"] for lg in shifted["legs"]] == [5, 3, 2]
        assert _hold_gap(shifted, 0) == 5
        assert _hold_gap(shifted, 1) == 3
    later = shift_plan(plan, 1, -14)
    assert later["legs"][0]["depart"] == "2026-10-01"
    assert later["legs"][0]["holdDays"] == 5
    assert _hold_gap(later, 0) == 5 - 14
    assert later["legs"][1]["holdDays"] == 3
    assert later["legs"][2]["holdDays"] == 2
    assert _hold_gap(later, 1) == 3


def test_two_calls_return_the_same_payload():
    plan = _noumea_chain()
    a = advise(plan, 0, now=NOW)
    b = advise(plan, 0, now=NOW)
    assert a == b
    assert a["best"]["sentence"] == b["best"]["sentence"]
    assert a["best"]["cascade"] == b["best"]["cascade"]


def test_sentence_numbers_all_live_in_facts():
    plan = _noumea_chain()
    out = advise(plan, 0, now=NOW)
    for cand in [out["best"], *out["alternatives"]]:
        blob = json.dumps(cand["facts"], ensure_ascii=False)
        nums = _numbers(cand["sentence"])
        assert nums, cand["sentence"]
        assert nums.issubset(_numbers(blob)), (nums - _numbers(blob), cand["sentence"])
        cleaned, dropped = filter_numbers(cand["sentence"], cand["facts"])
        assert dropped == 0
        assert cleaned
        assert "Nouméa" in cand["sentence"]
        assert str(abs(cand["shiftDays"])) in cand["sentence"] or cand["shiftDays"] == 0
        assert str(cand["alertsBefore"]) in cand["sentence"] or str(cand["alertsAfter"]) in cand["sentence"]


def test_sentence_names_leg_shift_alerts_and_cascade():
    plan = _noumea_chain()
    out = advise(plan, 0, now=NOW)
    text = out["best"]["sentence"]
    assert "Nouméa" in text
    assert "alertes" in text
    if out["best"]["shiftDays"] > 0:
        assert "reculent" in text
    elif out["best"]["shiftDays"] < 0:
        assert "avancent" in text
    else:
        assert "aucun décalage" in text
    assert "escales suivantes" in text


def test_frozen_leg_only_keeps_zero_shift():
    voy = load_official_mini()
    out = advise(voy, 0, now=NOW)
    assert out["best"]["shiftDays"] == 0
    assert out["alternatives"] == []


def test_request_advice_pending_then_done():
    plan = _noumea_chain()
    first = request_advice(plan, 0, now=NOW)
    assert first["status"] == "pending"
    assert first["weights"]["shiftPerDay"] == 0.3
    body = first
    for _ in range(80):
        body = request_advice(plan, 0, now=NOW)
        if body.get("status") == "done":
            break
        time.sleep(0.05)
    assert body["status"] == "done"
    assert body["best"]["score"] <= score_of(evaluate_plan(plan, now=NOW)["total"], 0, 0)
    again = request_advice(plan, 0, now=NOW)
    assert again == body


def test_rewrite_drops_llm_figures_absent_from_facts(monkeypatch):
    import voyage_api

    plan = _noumea_chain()
    payload = advise(plan, 0, now=NOW)
    gabarit = payload["best"]["sentence"]

    async def fake_cascade(system, user, client, **kwargs):
        return "Partir dans 99 jours avec 42 alertes.", "nemotron-lightning"

    monkeypatch.setattr("story_cascade.cascade_text", fake_cascade)
    out = voyage_api._rewrite_plan_advice(copy.deepcopy(payload))
    assert "99" not in out["best"]["sentence"]
    assert "42" not in out["best"]["sentence"]
    assert out["best"]["sentence"] == gabarit
    nums = _numbers(out["best"]["sentence"])
    assert nums.issubset(_numbers(json.dumps(out["best"]["facts"], ensure_ascii=False)))


def test_advice_route_pending_done_and_filter_numbers(monkeypatch):
    import voyage_api
    import voyage_store
    from fastapi.testclient import TestClient
    from main import app

    voyage_store.save_voyage(_official_with_leg3())
    monkeypatch.setattr(voyage_api, "_now", lambda: datetime(2026, 9, 22, 12, tzinfo=timezone.utc))

    async def fake_cascade(system, user, client, **kwargs):
        return "Partir dans 99 jours avec 42 alertes.", "nemotron-lightning"

    monkeypatch.setattr("story_cascade.cascade_text", fake_cascade)
    client = TestClient(app)
    first = client.get("/voyage/official/advice?leg=3")
    assert first.status_code == 200
    assert first.json()["status"] in ("pending", "done")
    body = first.json()
    for _ in range(80):
        if body.get("status") == "done":
            break
        time.sleep(0.05)
        body = client.get("/voyage/official/advice?leg=3").json()
    assert body["status"] == "done"
    assert body["leg"] == 3
    assert body["best"]["cascade"]
    assert body["best"]["cascade"][0]["stop"] == "Dzaoudzi"
    assert body["weights"] == {"shiftPerDay": 0.3, "extraNm": 0.02}
    nums = _numbers(body["best"]["sentence"])
    assert nums.issubset(_numbers(json.dumps(body["best"]["facts"], ensure_ascii=False)))
    assert "99" not in body["best"]["sentence"]
    assert "42" not in body["best"]["sentence"]
    missing = client.get("/voyage/official/advice?leg=9")
    assert missing.status_code == 200
    miss = missing.json()
    assert miss["status"] == "unavailable"
    assert miss["reason"] == "unknown_leg"
    assert miss["leg"] == 9


def _marks_no_clock():
    """Voyage avec marks (revue) mais sans clock.t0 — prepare_plan avait 0 jambe."""
    return {
        "voyageId": OFFICIAL_VOYAGE_ID,
        "t0": "2026-10-01T08:00:00Z",
        "official": True,
        "skipper_thresholds": TH,
        "marks": [
            {"name": "Nouméa", "nm": 0, "iso": "2026-10-01T08:00:00Z", "holdHours": 0},
            {"name": "Dzaoudzi", "nm": 80, "iso": "2026-10-02T08:00:00Z", "holdHours": 0},
            {"name": "Le Cap", "nm": 160, "iso": "2026-10-09T08:00:00Z", "holdHours": 0},
        ],
        "points": [
            {"lat": -22.27, "lon": 166.45, "sailNm": 0},
            {"lat": -21.9, "lon": 165.4, "sailNm": 40},
            {"lat": -21.6, "lon": 164.4, "sailNm": 80},
            {"lat": -27.0, "lon": 80.0, "sailNm": 120},
            {"lat": -33.92, "lon": 18.42, "sailNm": 160},
        ],
    }


def test_request_advice_no_clock_is_unavailable_not_http_error():
    voy = {"voyageId": "x"}
    out = request_advice(voy, 0, now=NOW)
    assert out["status"] == "unavailable"
    assert out["reason"] == "no_clock"
    assert out["leg"] == 0
    assert "best" not in out


def test_request_advice_accepts_review_index_without_clock():
    voy = _marks_no_clock()
    legs = review_legs(voy)
    assert len(legs) >= 1
    src, mapped, reason = resolve_advice_leg(voy, 0, now=NOW)
    assert reason == "no_clock"
    assert mapped is None
    assert (src.get("legs") or []) == []
    out = request_advice(voy, 0, now=NOW)
    assert out["status"] == "unavailable"
    assert out["reason"] == "no_clock"
    assert out["leg"] == 0


def test_request_advice_maps_review_index_onto_prepared_plan():
    voy = {
        "voyageId": OFFICIAL_VOYAGE_ID,
        "t0": "2026-10-01T08:00:00Z",
        "skipper_thresholds": TH,
        "marks": [
            {"name": "Nouméa", "nm": 0, "iso": "2026-10-01T08:00:00Z"},
            {"name": "Dzaoudzi", "nm": 80, "iso": "2026-10-02T08:00:00Z"},
            {"name": "Le Cap", "nm": 160, "iso": "2026-10-09T08:00:00Z"},
        ],
        "points": [
            {"lat": -22.27, "lon": 166.45, "sailNm": 0},
            {"lat": -21.6, "lon": 164.4, "sailNm": 80},
            {"lat": -33.92, "lon": 18.42, "sailNm": 160},
        ],
        "legs": [
            _leg(0, "Terre", "La Rochelle", "2026-05-01", "2026-05-14", 0, BISCAY_POINTS),
            _leg(1, "Nouméa", "Dzaoudzi", "2026-10-01", "2026-10-02", 5, NOUMEA_POINTS),
            _leg(2, "Dzaoudzi", "Le Cap", "2026-10-07", "2026-10-09", 3, DZAOUDZI_POINTS),
        ],
    }
    rev = review_legs(voy)
    assert [(lg["from"], lg["to"]) for lg in rev][0] == ("Nouméa", "Dzaoudzi")
    _src, mapped, reason = resolve_advice_leg(voy, 0, now=NOW)
    assert reason is None
    assert mapped == 1
    first = request_advice(voy, 0, now=NOW)
    assert first["status"] in ("pending", "done")
    assert first["leg"] == 0
    body = first
    for _ in range(80):
        if body.get("status") == "done":
            break
        time.sleep(0.05)
        body = request_advice(voy, 0, now=NOW)
    assert body["status"] == "done"
    assert body["leg"] == 0
    assert "Nouméa" in (body["best"].get("sentence") or "")


def test_advice_route_no_clock_returns_200_unavailable(monkeypatch):
    import voyage_api
    import voyage_store
    from fastapi.testclient import TestClient
    from main import app

    voyage_store.save_voyage(_marks_no_clock())
    monkeypatch.setattr(voyage_api, "_now", lambda: datetime(2026, 9, 22, 12, tzinfo=timezone.utc))
    client = TestClient(app)
    r = client.get("/voyage/official/advice?leg=0&lang=fr")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "unavailable"
    assert body["reason"] == "no_clock"
    assert body["leg"] == 0


# ── Écart local borné ─────────────────────────────────────────────

# La Rochelle → Gibraltar → Ajaccio ≈ 1 378 nm (le 1 371 du plan, ± 10).
LR_AJACCIO = [
    (46.15, -1.16),
    (36.10, -5.40),
    (41.92, 8.74),
]


def _lr_ajaccio_plan():
    pts = [{"lat": la, "lon": lo} for la, lo in LR_AJACCIO]
    return {
        "legs": [_leg(0, "La Rochelle", "Ajaccio", "2026-05-15", "2026-05-24", 3, pts)],
        "skipper_thresholds": {"galeKt": 30, "hsAlertM": 3.0},
    }


def test_corridors_stay_within_cap_and_300nm_of_reference():
    ref_nm = track_nm(LR_AJACCIO)
    assert 1360 <= ref_nm <= 1390
    seen = []
    for name in CORRIDORS:
        track = corridor_track(LR_AJACCIO, name)
        assert track is not None, name
        assert track_nm(track) <= ref_nm * DISTANCE_CAP_RATIO + 1e-6, (name, track_nm(track), ref_nm)
        for la, lo in track:
            assert distance_to_track_nm(la, lo, LR_AJACCIO) <= CORRIDOR_MAX_NM + 1e-6, (name, la, lo)
        seen.append(name)
    assert seen == ["reference", "north", "south"]
    north, south = corridor_track(LR_AJACCIO, "north"), corridor_track(LR_AJACCIO, "south")
    assert north != south
    mid_n = north[len(north) // 2]
    mid_s = south[len(south) // 2]
    assert mid_n[0] > mid_s[0]


def test_advise_candidates_never_exceed_distance_cap():
    plan = _lr_ajaccio_plan()
    out = advise(plan, 0, now=NOW)
    ref_nm = track_nm(LR_AJACCIO)
    for cand in [out["best"], *out["alternatives"]]:
        assert cand["corridor"] in CORRIDORS
        assert cand["extraNm"] <= ref_nm * (DISTANCE_CAP_RATIO - 1.0) + 1
        assert cand["score"] == score_of(cand["totalAfter"], cand["shiftDays"], cand["extraNm"])
    a = advise(plan, 0, now=NOW)
    assert a == out


def test_la_rochelle_ajaccio_wind30_at_most_1650():
    """Vent 40 kn partout, ordre 30 kn : sans borne l'isochrone errait (4 643 nm)."""
    t0 = datetime(2026, 5, 15, 8, tzinfo=timezone.utc)

    def wind(lat, lon, t):
        # Calme seulement très au nord — tentation d'écart libre vers l'Irlande.
        kn = 14.0 if lat >= 54.0 else 40.0
        return {"speedKnots": kn, "dirFromDeg": 270.0, "kind": "forecast", "hs": 1.0}

    out = bounded_isochrone(
        dep_lat=46.15, dep_lon=-1.16, dst_lat=41.92, dst_lon=8.74,
        departure_time=t0, wind_fn=wind, reference=LR_AJACCIO,
        wind_max_kt=30, time_step_h=6, heading_step_deg=20, max_steps=40,
    )
    assert out["distance_nm"] <= 1650
    coords = out["draft_geojson"]["geometry"]["coordinates"]
    assert coords
    for lon, lat in coords:
        assert distance_to_track_nm(lat, lon, LR_AJACCIO) <= CORRIDOR_MAX_NM + 5.0
    via_advise = advise(_lr_ajaccio_plan(), 0, now=NOW, wind_fn=wind, wind_max_kt=30)
    assert via_advise["best"]["extraNm"] <= track_nm(LR_AJACCIO) * 0.2 + 1
    if via_advise["best"].get("routeNm") is not None:
        assert via_advise["best"]["routeNm"] <= 1650


def test_no_proposed_date_before_now():
    """Aucun conseil dont la date est passée, ni sur une jambe déjà commencée."""
    from plan_advisor import departure_after_now, prepare_plan

    plan = _noumea_chain()
    now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
    prepared = prepare_plan(plan, now=now)
    assert prepared.get("_adviceClosed") in (None, [])
    out = advise(plan, 0, now=NOW)
    for cand in [out["best"], *out["alternatives"]]:
        shift = int(cand["shiftDays"])
        depart = datetime(2026, 10, 1, 8, tzinfo=timezone.utc) + timedelta(days=shift)
        assert depart > now, (shift, depart)
        assert departure_after_now({"departIso": depart.strftime("%Y-%m-%dT%H:%M:%SZ")}, now)

    started = "2026-10-05T12:00:00Z"
    src, mapped, reason = resolve_advice_leg(plan, 0, now=started)
    assert reason == "past"
    assert mapped is None
    assert 0 in (src.get("_adviceClosed") or [])
    blocked = request_advice(plan, 0, now=started)
    assert blocked["status"] == "unavailable"
    assert blocked["reason"] == "past"
    assert "best" not in blocked


def test_short_leg_rejects_north_south_over_cap():
    """Jambe courte (Nouméa) : un décalage de 150 nm dépasse +20 % → seuls les dates."""
    plan = _noumea_chain()
    assert corridor_track(NOUMEA_POINTS, "north") is None
    assert corridor_track(NOUMEA_POINTS, "south") is None
    out = advise(plan, 0, now=NOW)
    assert out["best"]["corridor"] == "reference"
    assert all(c["corridor"] == "reference" for c in out["alternatives"])
