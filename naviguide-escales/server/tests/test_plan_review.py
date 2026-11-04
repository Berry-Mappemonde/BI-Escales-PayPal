"""Revue de plan par règles : jambes, ZEE / ports d'entrée des perles, drapeaux honnêtes.

Commentaire U7 — faux LLM, aucun chiffre nouveau, cache par hash.
"""
import asyncio
from datetime import timedelta

import ici_engine
import ici_warm
import plan_review
import voyage_store
from ici_engine import thin_cache_key
from tests.test_voyage_journal import PUBLIC, T0, _freeze, _official, client  # noqa: F401
from voyage_clock import OFFICIAL_VOYAGE_ID

_LEGS = [{
    "from": "La Rochelle", "to": "Fort-de-France (Martinique)",
    "legNm": 3350, "daysAtSea": 14, "holdDays": 3,
    "ampCount": 1, "pearls": {"known": 10, "unknown": 4},
    "zees": [{"name": "French Exclusive Economic Zone", "gold": True, "poe": ["La Pallice"]}],
    "flags": [{"kind": "formalities", "names": ["Somewhere Exclusive Economic Zone"]}],
}]


def test_review_reads_calendar_and_pearls_without_inventing(client, monkeypatch):
    ici_engine.reset_caches()
    now = T0 + timedelta(days=10)
    _freeze(monkeypatch, now)
    client.put("/voyage/official", json=_official())
    voy = voyage_store.load_voyage(OFFICIAL_VOYAGE_ID)
    legs = plan_review.legs_from_clock(voy["clock"], "La Rochelle")
    assert len(legs) == 1
    leg = legs[0]
    assert leg["from"] == "La Rochelle" and leg["to"] == "Fort-de-France (Martinique)"
    assert leg["legNm"] == 3350 and leg["daysAtSea"] > 10
    # Warm half the pearls: French Gold EEZ with a port, then a zone without Gold nor port.
    pearls = ici_warm.sample_route_nm(voy["points"])
    fr = {"name": "French Exclusive Economic Zone", "mrgid": 5677, "gold": True}
    xx = {"name": "Somewhere Exclusive Economic Zone", "mrgid": 9999, "gold": False}
    for i, p in enumerate(pearls):
        if i >= len(pearls) // 2:
            break
        bag = {"zee": fr if i < 10 else xx, "poe": [{"name": "La Rochelle - La Pallice", "nm": 1.0}] if i < 10 else [], "amp": [], "sources": {"bi": "ok"}}
        ici_engine.thin_cache_put(thin_cache_key(p["lat"], p["lon"], 30.0), bag)
    out = plan_review.review_official(voy, now)
    leg = out["legs"][0]
    assert leg["pearls"]["known"] > 0 and leg["pearls"]["unknown"] > 0, "unknown pearls are counted, not guessed"
    names = {z["name"] for z in leg["zees"]}
    assert names == {"French Exclusive Economic Zone", "Somewhere Exclusive Economic Zone"}
    fr_z = next(z for z in leg["zees"] if z["mrgid"] == 5677)
    assert fr_z["gold"] is True and fr_z["poe"] == ["La Rochelle - La Pallice"]
    kinds = [f["kind"] for f in leg["flags"]]
    assert "formalities" in kinds, kinds
    assert next(f for f in leg["flags"] if f["kind"] == "formalities")["names"] == ["Somewhere Exclusive Economic Zone"]
    assert "no-rest" not in kinds, "3 days alongside at Fort-de-France"
    import official_store
    official_store.put("plan_review", out)
    body = client.get("/voyage/official/plan-review", headers=PUBLIC).json()
    assert body["legs"][0]["to"] == "Fort-de-France (Martinique)"
    assert body["pearlsUnknown"] == leg["pearls"]["unknown"]


def test_season_reads_the_atlas_cache_and_never_counts_zone_fallback(monkeypatch):
    import climatology_atlas as atlas
    clock = {"t0": "2026-05-15T08:00:00Z", "vertices": [
        {"tHours": 0, "sailNm": 0, "lat": 46.15, "lon": -1.16}, {"tHours": 50, "sailNm": 400, "lat": 44.0, "lon": -6.0},
        {"tHours": 100, "sailNm": 800, "lat": 40.0, "lon": -10.0},
    ]}
    leg = {"fromNm": 0, "toNm": 800, "month": 6}
    calls = []

    def fake(lat, lon, month, client=None):
        calls.append((lat, lon, month))
        if lat > 45:
            return {"source": "zone_fallback", "kind": "climatology"}
        return {"source": "atlas", "kind": "climatology", "point": {"rose": {"gale_pct": 17.5}, "cyclone": {"nearby": 2}}}

    monkeypatch.setattr(atlas, "atlas_wind_at", fake)
    s = plan_review.season_for_leg(clock, leg)
    assert s["cells"] == 2 and s["missing"] == 1, s
    assert s["galePct"] == 17.5 and s["cyclones"] == 2 and s["source"] == "atlas"
    assert all(m == 6 for _la, _lo, m in calls)
    # Out of budget: nothing read, nothing invented.
    import time
    late = plan_review.season_for_leg(clock, leg, budget_deadline=time.monotonic() - 1)
    assert late["cells"] == 0 and late["galePct"] is None


def test_comment_plan_write_tier_filter_and_cache(monkeypatch):
    calls = []

    async def fake_cascade(system, user, client=None, **kw):
        calls.append(kw)
        return (
            "Je changerais le repos à Fort-de-France (3 jours). "
            "La jambe fait 3350 nm. J'ajouterais 99 kn de vent.",
            "nemotron-super",
        )

    first = asyncio.run(plan_review.comment_plan(_LEGS, cascade=fake_cascade))
    assert first["source"] == "nemotron-super"
    assert first["cached"] is False
    assert "3350" in first["text"] and "3" in first["text"]
    assert "99" not in first["text"], "aucun chiffre inventé par le LLM"
    assert first["text"].count(".") <= 4

    again = asyncio.run(plan_review.comment_plan(_LEGS, cascade=fake_cascade))
    assert again["cached"] is True
    assert again["text"] == first["text"]
    assert len(calls) == 1, "cache par hash du tableau"

    other = [{**_LEGS[0], "legNm": 2000}]
    third = asyncio.run(plan_review.comment_plan(other, cascade=fake_cascade))
    assert third["cached"] is False
    assert len(calls) == 2


def test_comment_fallback_uses_only_table_numbers():
    facts = plan_review.table_facts(_LEGS)
    text = plan_review.comment_fallback(facts)
    assert "3350" in text and "14" in text
    assert "99" not in text
    assert len([s for s in text.split(".") if s.strip()]) <= 4


def _official_clock_compressed():
    """Itinéraire officiel (nm publiés) avec une horloge comprimée à 4,5 j / jambe.

    C'est le bug vu en recette : Nouméa → Dzaoudzi affichait 4,5 j de mer
    (écart d'horloge, ou dernier tronçon Seychelles → Dzaoudzi ≈ 883 nm)
    au lieu de 9 151 nm ÷ 8 kn ÷ 24.
    """
    stops = [
        ("La Rochelle", 0, 0),
        ("Ajaccio (Corse)", 1820, 1942),
        ("Fort-de-France (Martinique)", 6973, 7095),
        ("Nouméa (Nouvelle-Calédonie)", 19055, 19177),
        ("Dzaoudzi (Mayotte)", 28206, 28328),
        ("Tromelin (TAAF)", 29131, 29253),
        ("Saint-Gilles (La Réunion)", 29453, 29575),
        ("Europa (TAAF)", 30910, 31032),
        ("La Rochelle", 39000, 39122),
    ]
    t = 0.0
    verts = [{"tHours": 0.0, "sailNm": 0.0}]
    marks = []
    for i, (name, nm, film) in enumerate(stops):
        if i == 0:
            continue
        t += 4.5 * 24
        verts.append({"tHours": t, "sailNm": float(nm)})
        marks.append({
            "name": name, "tHours": t, "holdHours": 72,
            "nm": float(nm), "filmNm": float(film),
        })
        t += 72
        verts.append({"tHours": t, "sailNm": float(nm)})
    return {"t0": "2026-05-15T08:00:00Z", "vertices": verts, "marks": marks}


def test_sea_days_follow_clock_gap_on_official_legs():
    """R11 inversé : daysAtSea = écart départ → arrivée dès qu'il est positif."""
    from datetime import datetime, timezone

    clock = _official_clock_compressed()
    legs = plan_review.legs_from_clock(clock, "La Rochelle")
    assert legs, "jambes officielles attendues"
    assert plan_review.PLANNED_KNOTS == 8.0
    noumea = None
    for leg in legs:
        dep = datetime.fromisoformat(leg["departIso"].replace("Z", "+00:00"))
        arr = datetime.fromisoformat(leg["arriveIso"].replace("Z", "+00:00"))
        if dep.tzinfo is None:
            dep = dep.replace(tzinfo=timezone.utc)
        if arr.tzinfo is None:
            arr = arr.replace(tzinfo=timezone.utc)
        gap = (arr - dep).total_seconds() / 86400.0
        assert gap > 0, f"{leg['from']} → {leg['to']}"
        assert leg["daysAtSea"] == round(gap, 1), (
            f"{leg['from']} → {leg['to']}: {leg['daysAtSea']} j ≠ écart {gap:.2f} j"
        )
        if "Nouméa" in str(leg["from"]) and "Dzaoudzi" in str(leg["to"]):
            noumea = leg
    assert noumea is not None, [f"{l['from']}→{l['to']}" for l in legs]
    assert noumea["legNm"] == 9151
    assert noumea["daysAtSea"] == 4.5


def test_sea_days_use_itinerary_nm_when_clock_sailnm_collapsed():
    """Dernier tronçon geojson (Seychelles → Dzaoudzi ≈ 883 nm) ne doit pas gagner."""
    clock = {
        "t0": "2026-05-15T08:00:00Z",
        "vertices": [
            {"tHours": 0, "sailNm": 19055},
            {"tHours": 108, "sailNm": 19938},
        ],
        "marks": [
            {"name": "Nouméa (Nouvelle-Calédonie)", "tHours": 0, "holdHours": 0,
             "nm": 19055, "filmNm": 19177},
            {"name": "Dzaoudzi (Mayotte)", "tHours": 108, "holdHours": 72,
             "nm": 28206, "filmNm": 28328},
        ],
    }
    legs = plan_review.legs_from_clock(clock, "Nouméa (Nouvelle-Calédonie)")
    assert len(legs) == 1
    assert legs[0]["legNm"] == 9151
    assert legs[0]["daysAtSea"] == 4.5


def test_review_official_exposes_gibraltar_antishipping():
    clock = {
        "t0": "2026-05-15T08:00:00Z",
        "vertices": [
            {"tHours": 0, "sailNm": 1820, "lat": 41.92, "lon": 8.74},
            {"tHours": 40, "sailNm": 2500, "lat": 36.05, "lon": -5.6},
            {"tHours": 80, "sailNm": 4000, "lat": 29.3, "lon": -15.2},
            {"tHours": 200, "sailNm": 6973, "lat": 14.59, "lon": -61.07},
        ],
        "marks": [
            {"name": "Ajaccio (Corse)", "tHours": 0, "holdHours": 0, "nm": 1820, "filmNm": 1942},
            {"name": "Fort-de-France (Martinique)", "tHours": 200, "holdHours": 72, "nm": 6973, "filmNm": 7095},
        ],
    }
    voy = {"voyageId": "n3", "clock": clock, "points": [], "marks": []}
    out = plan_review.review_official(voy, season=False)
    assert len(out["legs"]) == 1
    pack = out["legs"][0]["antiShipping"]
    assert "Gibraltar" in pack["lanes"], pack
    assert 0 <= pack["score"] < 1
    facts = plan_review.table_facts(out["legs"])
    assert facts["legs"][0]["antiShipping"]["lanes"] == pack["lanes"]


def test_review_official_without_clock_builds_legs_and_names_gibraltar():
    """Semis sans clock → jambes depuis marks + t0 + points."""
    voy = {
        "voyageId": "seed-no-clock",
        "t0": "2026-05-15T08:00:00Z",
        "marks": [
            {"name": "Saint-Maur (Berry, Indre)", "nm": 0, "filmNm": 0},
            {"name": "La Rochelle", "nm": 122, "filmNm": 122},
            {"name": "Ajaccio (Corse)", "nm": 1942, "filmNm": 1942},
            {"name": "Fort-de-France (Martinique)", "nm": 7095, "filmNm": 7095},
        ],
        "points": [
            {"lat": 46.8, "lon": 1.6, "cumNm": 0, "nonMaritime": True},
            {"lat": 46.15, "lon": -1.16, "cumNm": 122, "nonMaritime": True},
            {"lat": 44.0, "lon": -2.0, "cumNm": 400},
            {"lat": 41.92, "lon": 8.74, "cumNm": 1942},
            {"lat": 36.05, "lon": -5.6, "cumNm": 2500},
            {"lat": 29.3, "lon": -15.2, "cumNm": 4000},
            {"lat": 14.59, "lon": -61.07, "cumNm": 7095},
        ],
    }
    assert "clock" not in voy
    out = plan_review.review_official(voy, season=False)
    pairs = [(leg["from"], leg["to"]) for leg in out["legs"]]
    assert pairs, "jambes attendues sans clock"
    assert not any("Saint-Maur" in a and "La Rochelle" in b for a, b in pairs)
    assert any("Ajaccio" in a and "Fort-de-France" in b for a, b in pairs), pairs
    aj = next(leg for leg in out["legs"] if "Ajaccio" in leg["from"] and "Fort-de-France" in leg["to"])
    assert "Gibraltar" in ((aj.get("antiShipping") or {}).get("lanes") or []), aj


def test_plan_review_seeded_without_clock_has_legs(client, monkeypatch):
    """Voyage semé sans clock → GET /plan-review 200, jambes, Ajaccio."""
    import voyage_api
    import voyage_clock

    voy = voyage_api.seed_official_voyage()
    assert voy is not None
    assert voy.get("clock") is None
    assert any("Ajaccio" in (m.get("name") or "") for m in voy.get("marks") or [])

    def boom(*_a, **_k):
        raise AssertionError("build_voyage_clock sur le thread HTTP")

    monkeypatch.setattr(voyage_clock, "build_voyage_clock", boom)
    monkeypatch.setattr(voyage_api, "_climo_clock", boom)

    async def fake_comment(legs, **_kw):
        return {"text": "", "source": "rules", "cached": False}

    monkeypatch.setattr(plan_review, "comment_plan", fake_comment)
    import official_store
    official_store.put("plan_review", plan_review.review_official(voy, season=False))
    r = client.get("/voyage/official/plan-review", headers=PUBLIC)
    assert r.status_code == 200
    body = r.json()
    assert len(body.get("legs") or []) > 0
    blob = " ".join(f"{leg.get('from')} {leg.get('to')}" for leg in body["legs"])
    assert "Ajaccio" in blob


def test_plan_review_http_exposes_comment_source(client, monkeypatch):
    async def fake_comment(legs, **kw):
        return {"text": "Je changerais le repos (3 jours).", "source": "rules", "cached": False}

    monkeypatch.setattr(plan_review, "comment_plan", fake_comment)
    now = T0 + timedelta(days=10)
    _freeze(monkeypatch, now)
    client.put("/voyage/official", json=_official())
    import official_store
    voy = voyage_store.load_voyage(OFFICIAL_VOYAGE_ID)
    out = plan_review.review_official(voy, now, season=False)
    out["comment"] = {"text": "Je changerais le repos (3 jours).", "source": "rules", "cached": False}
    official_store.put("plan_review", out)
    body = client.get("/voyage/official/plan-review", headers=PUBLIC).json()
    assert "comment" in body
    assert body["comment"]["source"] == "rules"
    assert "99" not in (body["comment"].get("text") or "")


def test_noumea_dzaoudzi_eta_interval_is_a_few_days():
    """Un membre à ~0 kn ne doit plus ouvrir 7 mois sur Nouméa → Dzaoudzi."""
    from datetime import datetime, timezone

    from ensemble_eta import (
        ETA_MAX_SPAN_DAYS,
        ETA_MIN_KN,
        arrival_quantiles,
        bound_eta_quantiles,
        implied_speed_kn,
        tighten_eta_arrivals,
    )
    from voyage_clock import PLANNING_MIN_KN

    now = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)
    remaining = 9151.0
    assert plan_review.ETA_MIN_KN == PLANNING_MIN_KN == ETA_MIN_KN == 3.0
    assert plan_review.ETA_MAX_SPAN_DAYS == ETA_MAX_SPAN_DAYS == 7.0
    healthy = [now + timedelta(days=47.7 + (i - 40) * 0.05) for i in range(80)]
    dead = now + timedelta(days=remaining / 0.5 / 24)
    arrivals = [dead] + healthy[1:]
    kept = tighten_eta_arrivals(arrivals, remaining_nm=remaining, now=now)
    assert dead not in kept
    assert all(implied_speed_kn(remaining, now, a) >= ETA_MIN_KN for a in kept)
    p10, p50, p90 = bound_eta_quantiles(*arrival_quantiles(kept))
    span = (p90 - p10).total_seconds() / 86400.0
    assert span <= plan_review.ETA_MAX_SPAN_DAYS + 1e-6
    assert plan_review.eta_span_days(p10.isoformat(), p90.isoformat()) <= 7.01
    assert plan_review.eta_span_days(None, p90.isoformat()) is None


def test_pacific_leg_origin_is_cayenne_after_episode():
    """Après l'épisode, la jambe Pacifique part de Cayenne, pas de Saint-Pierre."""
    from voyage_clock import build_voyage_clock

    def wind_fn(lat, lon, t):
        return {"speedKnots": 10.0, "dirFromDeg": 90.0, "kind": "climatology"}

    points = [
        {"lat": 4.93, "lon": -52.35, "cumNm": 1000, "filmCum": 1000, "jump": False},
        {"lat": 44.65, "lon": -63.57, "cumNm": 1000, "filmCum": 1080, "jump": True},
        {"lat": 46.78, "lon": -56.16, "cumNm": 1400, "filmCum": 1480, "jump": False},
        {"lat": 44.65, "lon": -63.57, "cumNm": 1800, "filmCum": 1880, "jump": False},
        {"lat": 4.93, "lon": -52.35, "cumNm": 1800, "filmCum": 1960, "jump": True},
        {"lat": 4.80, "lon": -52.50, "cumNm": 1830, "filmCum": 1990, "jump": False},
        {"lat": -17.54, "lon": -149.57, "cumNm": 5800, "filmCum": 6200, "jump": False},
    ]
    marks = [
        {"name": "Cayenne (Guyane)", "nm": 1000, "filmNm": 1000, "lat": 4.93, "lon": -52.35},
        {"name": "Saint-Pierre (Saint-Pierre-et-Miquelon)", "nm": 1400, "filmNm": 1480,
         "lat": 46.78, "lon": -56.16},
        {"name": "Papeete (Polynésie française)", "nm": 5800, "filmNm": 6200,
         "lat": -17.54, "lon": -149.57},
    ]
    clock = build_voyage_clock(
        points, marks, "2026-07-19T08:00:00Z", start_at="saint-maur", wind_fn=wind_fn,
    )
    legs = plan_review.legs_from_clock(clock, "Cayenne (Guyane)")
    pacific = [
        leg for leg in legs
        if "Papeete" in str(leg.get("to") or "") and "Papeete" not in str(leg.get("from") or "")
    ]
    assert pacific, [(leg["from"], leg["to"]) for leg in legs]
    assert "Cayenne" in str(pacific[0]["from"])
    assert "Saint-Pierre" not in str(pacific[0]["from"])
    assert "Miquelon" not in str(pacific[0]["from"])


def test_noumea_dzaoudzi_leg_unchanged_rc37():
    """RC37 : Nouméa → Dzaoudzi reste 9 151 nm ; l'épisode SPM ne le touche pas."""
    clock = {
        "t0": "2026-05-15T08:00:00Z",
        "vertices": [
            {"tHours": 0, "sailNm": 19055},
            {"tHours": 108, "sailNm": 19938},
        ],
        "marks": [
            {"name": "Nouméa (Nouvelle-Calédonie)", "tHours": 0, "holdHours": 0,
             "nm": 19055, "filmNm": 19177},
            {"name": "Dzaoudzi (Mayotte)", "tHours": 108, "holdHours": 72,
             "nm": 28206, "filmNm": 28328},
        ],
    }
    legs = plan_review.legs_from_clock(clock, "Nouméa (Nouvelle-Calédonie)")
    assert len(legs) == 1
    assert "Nouméa" in legs[0]["from"] and "Dzaoudzi" in legs[0]["to"]
    assert legs[0]["legNm"] == 9151


def _rc54_scrambled_pacific_voy():
    """Marques Mata-Utu / Nouméa collées sur le retour atlantique (tHours faux),
    sommets justes aux milles d'itinéraire — bug vu le 16 oct. en Revue du plan."""
    clock = {
        "t0": "2026-05-15T08:00:00Z",
        "vertices": [
            {"tHours": 0, "sailNm": 122, "lat": 46.15, "lon": -1.17, "vehicle": "main"},
            {"tHours": 200, "sailNm": 800, "lat": 44.5, "lon": -5.0, "vehicle": "main"},
            {"tHours": 400, "sailNm": 2000, "lat": 40.0, "lon": -30.0, "vehicle": "main"},
            {"tHours": 3422, "sailNm": 16205, "lat": -17.51, "lon": -149.57, "vehicle": "main"},
            {"tHours": 3680, "sailNm": 17847, "lat": -13.27, "lon": -176.20, "vehicle": "main"},
            {"tHours": 3750, "sailNm": 18500, "lat": -18.0, "lon": 178.0, "vehicle": "main"},
            {"tHours": 3858, "sailNm": 19177, "lat": -22.30, "lon": 166.46, "vehicle": "main"},
            {"tHours": 8406, "sailNm": 38024, "lat": 28.12, "lon": -16.16, "vehicle": "main"},
            {"tHours": 8600, "sailNm": 38500, "lat": 44.0, "lon": -40.0, "vehicle": "main"},
            {"tHours": 8800, "sailNm": 38800, "lat": 45.0, "lon": -5.0, "vehicle": "main"},
            {"tHours": 8924, "sailNm": 38993, "lat": 42.93, "lon": -9.77, "vehicle": "main"},
            {"tHours": 9162, "sailNm": 39426, "lat": 46.15, "lon": -1.17, "vehicle": "main"},
        ],
        "marks": [
            {"name": "Papeete (Polynésie française)", "tHours": 3422, "holdHours": 72,
             "lat": -17.51, "lon": -149.57},
            {"name": "Mata-Utu (Wallis-et-Futuna)", "tHours": 8406, "holdHours": 72,
             "lat": 28.12, "lon": -376.16},
            {"name": "Nouméa (Nouvelle-Calédonie)", "tHours": 8924, "holdHours": 72,
             "lat": 42.93, "lon": -369.77},
            {"name": "La Rochelle", "tHours": 9162, "holdHours": 72,
             "lat": 46.15, "lon": -361.17},
        ],
    }
    return {
        "voyageId": "rc54",
        "t0": clock["t0"],
        "clock": clock,
        "marks": [
            {"name": "Papeete (Polynésie française)", "nm": 16205, "filmNm": 16365,
             "lat": -17.51, "lon": -149.57},
            {"name": "Mata-Utu (Wallis-et-Futuna)", "nm": 17847, "filmNm": 18007,
             "lat": -13.27, "lon": -176.20},
            {"name": "Nouméa (Nouvelle-Calédonie)", "nm": 19177, "filmNm": 19337,
             "lat": -22.30, "lon": 166.46},
            {"name": "La Rochelle", "nm": 39426, "filmNm": 39586,
             "lat": 46.15, "lon": -1.17},
        ],
        "points": [
            {"lat": 46.15, "lon": -1.17, "cumNm": 122},
            {"lat": 44.5, "lon": -5.0, "cumNm": 800},
            {"lat": 40.0, "lon": -30.0, "cumNm": 2000},
            {"lat": -17.51, "lon": -149.57, "cumNm": 16205},
            {"lat": -13.27, "lon": -176.20, "cumNm": 17847},
            {"lat": -18.0, "lon": 178.0, "cumNm": 18500},
            {"lat": -22.30, "lon": 166.46, "cumNm": 19177},
            {"lat": 28.12, "lon": -16.16, "cumNm": 38024},
            {"lat": 44.0, "lon": -40.0, "cumNm": 38500},
            {"lat": 45.0, "lon": -5.0, "cumNm": 38800},
            {"lat": 46.15, "lon": -1.17, "cumNm": 39426},
        ],
    }


def test_mata_utu_noumea_has_no_atlantic_lanes():
    """Mata-Utu → Nouméa n'a ni Bay of Biscay ni N Atlantic."""
    out = plan_review.review_official(_rc54_scrambled_pacific_voy(), season=False)
    pacific = [
        lg for lg in out["legs"]
        if "Mata-Utu" in str(lg.get("from") or "") and "Nouméa" in str(lg.get("to") or "")
    ]
    assert pacific, [(lg["from"], lg["to"]) for lg in out["legs"]]
    leg = pacific[0]
    lanes = ((leg.get("antiShipping") or {}).get("lanes") or [])
    blob = " ".join(lanes)
    assert "Bay of Biscay" not in blob, lanes
    assert "N Atlantic" not in blob, lanes
    assert leg["legNm"] == 1330


def test_noumea_la_rochelle_dates_match_sea_days():
    """Nouméa → La Rochelle, jours de mer et (arrivée − départ) sans facteur dix."""
    from datetime import datetime, timezone

    clock = {
        "t0": "2026-05-15T08:00:00Z",
        "vertices": [
            {"tHours": 288, "sailNm": 38993, "lat": 42.93, "lon": -9.77, "vehicle": "main"},
            {"tHours": 360, "sailNm": 39426, "lat": 46.15, "lon": -1.17, "vehicle": "main"},
        ],
        "marks": [
            {"name": "Nouméa (Nouvelle-Calédonie)", "tHours": 288, "holdHours": 0,
             "nm": 19177, "filmNm": 19337},
            {"name": "La Rochelle", "tHours": 360, "holdHours": 0,
             "nm": 39426, "filmNm": 39586},
        ],
    }
    legs = plan_review.legs_from_clock(clock, "Nouméa (Nouvelle-Calédonie)")
    row = [
        lg for lg in legs
        if "Nouméa" in str(lg.get("from") or "") and "La Rochelle" in str(lg.get("to") or "")
    ]
    assert row, [(lg["from"], lg["to"]) for lg in legs]
    leg = row[0]
    dep = datetime.fromisoformat(leg["departIso"].replace("Z", "+00:00"))
    arr = datetime.fromisoformat(leg["arriveIso"].replace("Z", "+00:00"))
    if dep.tzinfo is None:
        dep = dep.replace(tzinfo=timezone.utc)
    if arr.tzinfo is None:
        arr = arr.replace(tzinfo=timezone.utc)
    span = (arr - dep).total_seconds() / 86400.0
    days = float(leg["daysAtSea"])
    lo, hi = (span, days) if span < days else (days, span)
    assert hi / max(lo, 1e-9) < 10.0, (
        f"{leg['departIso'][:10]} → {leg['arriveIso'][:10]} = {span:.1f} j "
        f"contre {days} j de mer ({leg['legNm']} nm)"
    )


def test_sea_days_follow_clock_gap():
    """daysAtSea suit l'écart d'horloge (départ → arrivée), pas milles ÷ 8 kn."""
    from datetime import datetime, timezone

    gap_h = 11 * 24
    clock = {
        "t0": "2026-05-15T08:00:00Z",
        "vertices": [
            {"tHours": 0, "sailNm": 0, "lat": 46.15, "lon": -1.17, "vehicle": "main"},
            {"tHours": gap_h, "sailNm": 1920, "lat": 41.92, "lon": 8.74, "vehicle": "main"},
        ],
        "marks": [
            {"name": "La Rochelle", "tHours": 0, "holdHours": 0, "nm": 0, "filmNm": 0},
            {"name": "Ajaccio (Corse)", "tHours": gap_h, "holdHours": 72, "nm": 1920, "filmNm": 1920},
        ],
    }
    legs = plan_review.legs_from_clock(clock, "La Rochelle")
    assert len(legs) == 1
    leg = legs[0]
    dep = datetime.fromisoformat(leg["departIso"].replace("Z", "+00:00"))
    arr = datetime.fromisoformat(leg["arriveIso"].replace("Z", "+00:00"))
    if dep.tzinfo is None:
        dep = dep.replace(tzinfo=timezone.utc)
    if arr.tzinfo is None:
        arr = arr.replace(tzinfo=timezone.utc)
    gap = (arr - dep).total_seconds() / 86400.0
    assert gap == 11
    assert leg["daysAtSea"] == 11
    planned = plan_review.planned_sea_days(1920)
    assert planned == 10.0
    assert leg["daysAtSea"] != planned

    voy = {
        "t0": "2026-05-15T08:00:00Z",
        "marks": [
            {"name": "La Rochelle", "nm": 0},
            {"name": "Ajaccio (Corse)", "nm": 1920},
        ],
        "points": [
            {"lat": 46.15, "lon": -1.17, "cumNm": 0},
            {"lat": 41.92, "lon": 8.74, "cumNm": 1920},
        ],
    }
    fallback = plan_review.legs_from_voyage(voy)
    assert len(fallback) == 1
    assert fallback[0]["daysAtSea"] == planned


def test_r11_sea_days_use_clock_gap_beyond_ten_percent():
    """R11 inversé : un écart positif l'emporte sur milles ÷ 8 kn, même à +50 %."""
    from datetime import datetime, timezone

    dep = datetime(2026, 5, 15, 8, tzinfo=timezone.utc)
    arr = datetime(2026, 5, 30, 8, tzinfo=timezone.utc)
    assert plan_review.planned_sea_days(1920) == 10.0
    assert plan_review.sea_days_between(dep, arr, 1920, from_clock=True) == 15.0
    short = datetime(2026, 5, 17, 8, tzinfo=timezone.utc)
    assert plan_review.sea_days_between(dep, short, 1920, from_clock=True) == 2.0


def test_sea_days_fall_back_to_8_kn_only_without_usable_dates():
    from datetime import datetime, timezone

    dep = datetime(2026, 5, 15, 8, tzinfo=timezone.utc)
    before = datetime(2026, 5, 10, 8, tzinfo=timezone.utc)
    assert plan_review.sea_days_between(dep, dep, 1920, from_clock=True) == 10.0
    assert plan_review.sea_days_between(dep, before, 1920, from_clock=True) == 10.0
    assert plan_review.sea_days_between(None, dep, 1920, from_clock=True) == 10.0
    assert plan_review.sea_days_between(dep, None, 1920, from_clock=True) == 10.0
    assert plan_review.sea_days_between(dep, before, 1920, from_clock=False) == 10.0


def test_voyage_without_clock_uses_real_iso_gap():
    voy = {"t0": "2026-05-15T08:00:00Z",
           "marks": [{"name": "La Rochelle", "nm": 0, "iso": "2026-05-15T10:00:00+02:00"},
                     {"name": "Ajaccio (Corse)", "nm": 1920, "iso": "2026-05-27T08:00:00Z"}],
           "points": [{"lat": 46.15, "lon": -1.17, "cumNm": 0}, {"lat": 41.92, "lon": 8.74, "cumNm": 1920}]}
    assert plan_review.legs_from_voyage(voy)[0]["daysAtSea"] == 12.0
