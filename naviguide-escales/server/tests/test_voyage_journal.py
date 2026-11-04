"""Journal serveur du voyage officiel — mémoire honnête, jamais inventée."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import admin_guard
import forecast_cube
import saildocs
import voyage_api
import voyage_journal as journal
import voyage_store
from voyage_clock import OFFICIAL_T0, OFFICIAL_VOYAGE_ID, parse_iso

PUBLIC = {"X-Real-IP": "203.0.113.7", "X-Forwarded-For": "203.0.113.7"}
T0 = parse_iso(OFFICIAL_T0)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_FORECAST_BACKEND", "synthetic")
    monkeypatch.setenv("NAVIGUIDE_VOYAGE_DIR", str(tmp_path / "voyages"))
    monkeypatch.setenv("NAVIGUIDE_FORECAST_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("NAVIGUIDE_GRIB_DIR", str(tmp_path / "grib"))
    monkeypatch.setenv("NAVIGUIDE_GRIB_AUTO", "0")
    monkeypatch.delenv(admin_guard.ADMIN_ENV, raising=False)
    voyage_store._DIR = tmp_path / "voyages"
    forecast_cube.CACHE_DIR = tmp_path / "cache"
    saildocs.GRIB_DIR = tmp_path / "grib"
    journal.reset()
    admin_guard.reset_limiters()
    from main import app
    return TestClient(app)


def _official():
    return {
        "t0": OFFICIAL_T0,
        "expedition_id": "berry-mappemonde-2026",
        "routeKind": "berry",
        "follow": True,
        "forecast": False,
        "startAt": "la-rochelle",
        "official": True,
        "points": [
            {"lat": 46.15, "lon": -1.16, "cumNm": 0, "filmCum": 0, "jump": False, "nonMaritime": False},
            {"lat": 40.0, "lon": -15.0, "cumNm": 650, "filmCum": 650, "jump": False, "nonMaritime": False},
            {"lat": 28.0, "lon": -30.0, "cumNm": 1450, "filmCum": 1450, "jump": False, "nonMaritime": False},
            {"lat": 14.6, "lon": -61.07, "cumNm": 3350, "filmCum": 3350, "jump": False, "nonMaritime": False},
        ],
        "marks": [
            {"name": "La Rochelle", "nm": 0, "filmNm": 0, "lat": 46.15, "lon": -1.16, "index": 0},
            {"name": "Fort-de-France (Martinique)", "nm": 3350, "filmNm": 3350, "lat": 14.6, "lon": -61.07, "index": 3},
        ],
    }


def _freeze(monkeypatch, when: datetime):
    monkeypatch.setattr(voyage_api, "_now", lambda: when)


def test_positions_every_six_hours_from_t0_and_idempotent(client, monkeypatch):
    now = T0 + timedelta(days=2, hours=5)  # 2026-05-17T13:00Z
    _freeze(monkeypatch, now)
    client.put("/voyage/official", json=_official())
    voy = voyage_store.load_voyage(OFFICIAL_VOYAGE_ID)

    first = journal.tick(voy, now, force=True)
    assert first["positions"] == 10  # 15/05 06 12 18 · 16/05 ×4 · 17/05 00 06 12
    again = journal.tick(voy, now, force=True)
    assert again["positions"] == 0

    days = journal.list_days()
    assert [d["day"] for d in days] == ["2026-05-15", "2026-05-16", "2026-05-17"]
    entries = journal.read_day("2026-05-16")
    assert [e["t"][11:13] for e in entries if e["kind"] == "position"] == ["00", "06", "12"] + ["18"]
    sample = entries[0]
    assert sample["basis"] == "clock"
    assert sample["lat"] is not None and sample["lon"] is not None
    assert sample["status"] in ("live", "waiting", "arrived")

    # The next day brings only the missing slots.
    later = now + timedelta(hours=13)  # 2026-05-18T02:00Z → 17/05 18h, 18/05 00h
    assert journal.tick(voy, later, force=True)["positions"] == 2


def test_stops_are_recorded_once_passed(client, monkeypatch):
    client.put("/voyage/official", json=_official())
    voy = voyage_store.load_voyage(OFFICIAL_VOYAGE_ID)
    marks = voy["clock"]["marks"]
    assert marks and marks[-1]["name"].startswith("Fort-de-France")
    arrival = T0 + timedelta(hours=float(marks[-1]["tHours"]))

    before = journal.record_stops(voy["clock"], arrival - timedelta(hours=1))
    assert before == 0
    after = journal.record_stops(voy["clock"], arrival + timedelta(hours=1))
    assert after >= 1
    stops = journal.latest(10, kinds=["stop"])
    assert stops[0]["event"] == "arrival"
    assert stops[0]["name"].startswith("Fort-de-France")
    assert stops[0]["basis"] == "clock"
    assert journal.record_stops(voy["clock"], arrival + timedelta(hours=1)) == 0


def test_grib_at_the_boat_once_per_cycle(client, monkeypatch):
    now = T0 + timedelta(days=3)
    _freeze(monkeypatch, now)
    client.put("/voyage/official", json=_official())
    voy = voyage_store.load_voyage(OFFICIAL_VOYAGE_ID)
    record = {
        "status": "ready",
        "cycle": "2026-05-18T06:00:00Z",
        "model": "GFS",
        "source": "openmeteo",
        "samples": [{
            "lat": 44.0, "lon": -6.0, "t": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "windKnots": 14.2, "dirFromDeg": 250, "pressHpa": 1013.2, "rainMm": 0.2, "hs": 1.1,
        }],
    }
    assert journal.record_grib(record, voy["clock"], now) is True
    assert journal.record_grib(record, voy["clock"], now) is False  # same cycle
    assert journal.record_grib({"status": "pending"}, voy["clock"], now) is False
    g = journal.latest(5, kinds=["grib"])[0]
    assert g["windKnots"] == 14.2 and g["hs"] == 1.1 and g["basis"] == "forecast"
    assert g["cycle"] == "2026-05-18T06:00:00Z"


def test_public_reads_and_admin_note(client, monkeypatch):
    now = T0 + timedelta(days=1)
    _freeze(monkeypatch, now)
    client.put("/voyage/official", json=_official())
    voy = voyage_store.load_voyage(OFFICIAL_VOYAGE_ID)
    journal.tick(voy, now, force=True)

    r = client.get("/voyage/official/journal", headers=PUBLIC)
    assert r.status_code == 200
    body = r.json()
    assert body["voyageId"] == OFFICIAL_VOYAGE_ID
    assert body["count"] >= 4
    assert body["latest"][0]["t"] >= body["latest"][-1]["t"]  # newest first
    assert body["days"][0]["day"] == "2026-05-15"

    day = client.get(f"/voyage/official/journal/{body['days'][0]['day']}", headers=PUBLIC)
    assert day.status_code == 200 and day.json()["entries"]
    assert client.get("/voyage/official/journal/2030-01-01", headers=PUBLIC).status_code == 404
    assert client.get("/voyage/official/journal/pas-un-jour", headers=PUBLIC).status_code == 400

    # Note : écriture humaine, admin seulement (503 sans secret derrière nginx).
    assert client.post("/voyage/official/journal/note", json={"text": "Départ !"}, headers=PUBLIC).status_code == 503
    monkeypatch.setenv(admin_guard.ADMIN_ENV, "s")
    assert client.post("/voyage/official/journal/note", json={"text": "Départ !"}, headers=PUBLIC).status_code == 401
    ok = client.post(
        "/voyage/official/journal/note",
        json={"text": "  Largué les amarres,   vent de NO.  ", "author": "Clément"},
        headers={**PUBLIC, admin_guard.ADMIN_HEADER: "s"},
    )
    assert ok.status_code == 200
    assert ok.json()["text"] == "Largué les amarres, vent de NO."
    assert ok.json()["author"] == "Clément"
    bad = client.post("/voyage/official/journal/note", json={"text": "   "}, headers={**PUBLIC, admin_guard.ADMIN_HEADER: "s"})
    assert bad.status_code == 400
    latest = client.get("/voyage/official/journal?limit=3", headers=PUBLIC).json()["latest"]
    assert latest[0]["kind"] == "note"


def test_tick_is_throttled_for_public_reads(client, monkeypatch):
    now = T0 + timedelta(days=1)
    _freeze(monkeypatch, now)
    client.put("/voyage/official", json=_official())
    voy = voyage_store.load_voyage(OFFICIAL_VOYAGE_ID)
    journal.reset()
    assert journal.tick(voy, now)["skipped"] is False
    assert journal.tick(voy, now)["skipped"] is True
    assert journal.tick(voy, now, force=True)["skipped"] is False
    assert journal.tick(None, now)["skipped"] is True


def test_route_events_from_warmed_pearls_dated_by_the_clock(client, monkeypatch):
    """v2 : ZEE franchies et AMP approchées lues sur les perles chauffées,
    datées par l'horloge ; une perle inconnue = trou honnête, pas d'invention."""
    import ici_engine
    import ici_warm
    from ici_engine import thin_cache_key

    ici_engine.reset_caches()
    now = T0 + timedelta(days=30)
    _freeze(monkeypatch, now)
    client.put("/voyage/official", json=_official())
    voy = voyage_store.load_voyage(OFFICIAL_VOYAGE_ID)
    pearls = ici_warm.sample_route_nm(voy["points"])
    assert len(pearls) > 100
    assert pearls[0]["sailNm"] == 0 and pearls[10]["sailNm"] > pearls[9]["sailNm"]

    # Warm the first 40 pearls: French EEZ, then high seas from pearl 20,
    # an MPA within reach at pearls 5-6, a gap (unknown) at pearls 12-13,
    # and a one-pearl gazetteer flap (high seas) at pearl 8.
    fr = {"name": "French Exclusive Economic Zone", "mrgid": 5677, "territory": "metropole"}
    for i, p in enumerate(pearls[:40]):
        if i in (12, 13):
            continue
        zee = None if (i >= 20 or i == 8) else fr
        amp = [{"name": "Pertuis charentais - Rochebonne", "site_id": "pc-1", "nm": 3.6, "iucn_cat": "II"}] if i in (5, 6) else []
        ici_engine.thin_cache_put(thin_cache_key(p["lat"], p["lon"], 30.0), {"zee": zee, "amp": amp, "sources": {"bi": "ok"}})

    events = ici_warm.route_events_from_pearls(voy["points"])
    kinds = [(e["kind"], e["event"], e["idx"]) for e in events]
    assert ("zee", "exit", 20) in kinds, kinds
    assert ("amp", "nearby", 5) in kinds
    assert not any(k[0] == "zee" and k[2] in (8, 9) for k in kinds), "un seul point en haute mer = bruit de gazetteer, pas une sortie"
    assert not any(k[0] == "zee" and k[2] in (12, 13, 14) for k in kinds), "aucune transition inventée autour du trou"
    assert sum(1 for k in kinds if k[0] == "zee") == 1, kinds
    assert sum(1 for k in kinds if k[0] == "amp") == 1, "une AMP racontée une fois"

    out = journal.tick(voy, now, force=True)
    assert out["routeEvents"] == 2
    latest = journal.latest(50, kinds=("zee", "amp"))
    zee = next(e for e in latest if e["kind"] == "zee")
    assert zee["event"] == "exit" and zee["name"].startswith("French")
    assert parse_iso(zee["t"]) > T0 and parse_iso(zee["t"]) <= now
    # Idempotent, and a later now does not duplicate.
    assert journal.tick(voy, now + timedelta(hours=1), force=True)["routeEvents"] == 0
    # The API lists the new kinds.
    body = client.get("/voyage/official/journal?limit=500").json()
    assert "zee" in body["kinds"] and "amp" in body["kinds"]
    assert any(e["kind"] == "amp" for e in body["latest"])


def test_summary_carries_the_whole_voyage_events_apart_from_positions(client, monkeypatch):
    client.put("/voyage/official", json=_official())
    voy = voyage_store.load_voyage(OFFICIAL_VOYAGE_ID)
    fdf = next(m for m in voy["clock"]["marks"] if "Fort-de-France" in m["name"])
    now = T0 + timedelta(hours=float(fdf["tHours"]) + 36)
    _freeze(monkeypatch, now)
    journal.tick(voy, now, force=True)
    journal.add_note("Belle étoile.", T0 + timedelta(days=1))
    body = client.get("/voyage/official/journal?limit=10").json()
    assert len(body["latest"]) == 10
    kinds = {e["kind"] for e in body["events"]}
    assert "position" not in kinds
    assert "stop" in kinds and "note" in kinds
    assert any(e["kind"] == "note" and e["text"] == "Belle étoile." for e in body["events"])


def test_lot_a_ports_of_entry_and_weather_lines(client, monkeypatch):
    """Ports d'entrée passés (perles) et météo marquante (dérivée du GRIB)."""
    import ici_engine
    import ici_warm
    from ici_engine import thin_cache_key

    ici_engine.reset_caches()
    now = T0 + timedelta(days=30)
    _freeze(monkeypatch, now)
    client.put("/voyage/official", json=_official())
    voy = voyage_store.load_voyage(OFFICIAL_VOYAGE_ID)
    pearls = ici_warm.sample_route_nm(voy["points"])
    fr = {"name": "French Exclusive Economic Zone", "mrgid": 5677}
    for i, p in enumerate(pearls[:12]):
        poe = [{"name": "La Rochelle - La Pallice", "id": "poe-lr", "nm": 1.6 if i < 2 else 40.0, "url": "https://douane.gouv.fr"}]
        ici_engine.thin_cache_put(thin_cache_key(p["lat"], p["lon"], 30.0), {"zee": fr, "amp": [], "poe": poe, "sources": {"bi": "ok"}})
    events = ici_warm.route_events_from_pearls(voy["points"])
    poes = [e for e in events if e["kind"] == "poe"]
    assert len(poes) == 1 and poes[0]["name"] == "La Rochelle - La Pallice" and poes[0]["idx"] == 0
    assert journal.tick(voy, now, force=True)["routeEvents"] == 1
    assert journal.latest(10, kinds=("poe",))[0]["event"] == "passed"

    # A GRIB reading above the gale line yields a wx line; a quiet one does not.
    assert journal.wx_entry_from_grib({"id": "grib:c1", "t": "2026-05-20T06:00:00Z", "windKnots": 12, "hs": 1.0}) is None
    wx = journal.wx_entry_from_grib({"id": "grib:c2", "t": "2026-05-21T06:00:00Z", "windKnots": 36.5, "dirFromDeg": 250, "hs": 2.0, "model": "GFS"})
    assert wx["kind"] == "wx" and wx["event"] == "gale" and wx["windKnots"] == 36.5 and wx["t"] == "2026-05-21T06:00:00Z"
    sea = journal.wx_entry_from_grib({"id": "grib:c3", "t": "2026-05-22T06:00:00Z", "windKnots": 20, "hs": 4.1})
    assert sea["event"] == "sea"
    # Journaled GRIBs are turned into wx lines by the tick, once.
    journal._append([{"id": "grib:c2", "kind": "grib", "t": "2026-05-21T06:00:00Z", "windKnots": 36.5, "dirFromDeg": 250, "hs": 2.0, "model": "GFS"}])
    assert journal.record_wx(now) == 1
    assert journal.record_wx(now) == 0
    body = client.get("/voyage/official/journal?limit=20&kinds=wx,poe").json()
    assert {e["kind"] for e in body["latest"]} == {"wx", "poe"}
    assert any(e["kind"] == "wx" for e in body["events"])


def test_pearl_lines_follow_the_current_reading_of_the_pearls(client, monkeypatch):
    """Quand une perle s'affine (thin → riche, meilleure ZEE), la lecture
    change : le journal garde la lecture courante, pas la pile des lectures."""
    import ici_engine
    import ici_warm
    from ici_engine import thin_cache_key

    ici_engine.reset_caches()
    now = T0 + timedelta(days=30)
    _freeze(monkeypatch, now)
    client.put("/voyage/official", json=_official())
    voy = voyage_store.load_voyage(OFFICIAL_VOYAGE_ID)
    pearls = ici_warm.sample_route_nm(voy["points"])
    fr = {"name": "French Exclusive Economic Zone", "mrgid": 5677}
    es = {"name": "Spanish Exclusive Economic Zone", "mrgid": 5693}
    # First reading: French then Spanish from pearl 10.
    for i, p in enumerate(pearls[:30]):
        ici_engine.thin_cache_put(thin_cache_key(p["lat"], p["lon"], 30.0), {"zee": fr if i < 10 else es, "amp": [], "poe": [], "sources": {"bi": "ok"}}, "thin")
    assert journal.tick(voy, now, force=True)["routeEvents"] == 2  # exit FR + enter ES at idx 10
    first = journal.latest(20, kinds=("zee",))
    assert {e["id"].split(":")[3] for e in first} == {"10"}
    # Second reading (rich pearls): the boundary is really at pearl 14.
    for i, p in enumerate(pearls[:30]):
        ici_engine.thin_cache_put(thin_cache_key(p["lat"], p["lon"], 30.0), {"zee": fr if i < 14 else es, "amp": [], "poe": [], "sources": {"bi": "ok"}}, "rich")
    journal.tick(voy, now, force=True)
    second = journal.latest(20, kinds=("zee",))
    assert len(second) == 2, [e["id"] for e in second]
    assert {e["id"].split(":")[3] for e in second} == {"14"}
    # Human and clock lines are untouched by the re-reading.
    assert journal.latest(500, kinds=("position",))


def test_lot_f2_climo_rose_turn_and_calms(client, monkeypatch):
    """Rose qui tourne de 120° → climo ; deux perles calmes → climo « calmes »."""
    import ici_engine
    import ici_warm
    from ici_engine import thin_cache_key

    ici_engine.reset_caches()
    now = T0 + timedelta(days=30)
    _freeze(monkeypatch, now)
    client.put("/voyage/official", json=_official())
    voy = voyage_store.load_voyage(OFFICIAL_VOYAGE_ID)
    pearls = ici_warm.sample_route_nm(voy["points"])

    def put(i, **climo):
        p = pearls[i]
        ici_engine.thin_cache_put(thin_cache_key(p["lat"], p["lon"], 30.0), {
            "zee": None, "amp": [], "poe": [],
            "climatology": climo,
            "science": {"nearby": []},
            "sources": {"bi": "ok"},
        })

    for i in range(4):
        put(i, rose={"most_likely": {"speed_knots": 16.0, "dir_deg": 30}, "stat": "rose"}, cyclone={"nearby": 0})
    put(4, rose={"most_likely": {"speed_knots": 15.0, "dir_deg": 150}, "stat": "rose"}, cyclone={"nearby": 0})
    events = ici_warm.route_events_from_pearls(voy["points"])
    roses = [e for e in events if e["kind"] == "climo" and e["event"] == "rose"]
    assert len(roses) == 1 and roses[0]["idx"] == 4
    assert roses[0]["facts"]["deltaDeg"] == 120
    assert roses[0]["title"]["fr"] == "Changement de régime"
    assert roses[0]["lat"] is not None and roses[0]["entity"]["kind"] == "climo"

    ici_engine.reset_caches()
    journal.reset()
    # Resample after reset: a seed/warm thread may have replaced the official
    # points; reset_caches() clears memory only, so drop the cells we seed.
    voy = voyage_store.load_voyage(OFFICIAL_VOYAGE_ID)
    pts = list(voy["points"])
    pearls = ici_warm.sample_route_nm(pts)
    assert len(pearls) >= 3
    for i in range(3):
        ici_engine.thin_cache_drop(thin_cache_key(pearls[i]["lat"], pearls[i]["lon"], 30.0))
        put(i, rose={"most_likely": {"speed_knots": 6.0, "dir_deg": 80}, "stat": "rose"}, cyclone={"nearby": 0})
    events = ici_warm.route_events_from_pearls(pts)
    calms = [e for e in events if e["kind"] == "climo" and e["event"] == "calms"]
    assert len(calms) == 1
    assert calms[0]["facts"]["windKn"] == 6.0
    out = journal.tick(voy, now, force=True)
    assert out["routeEvents"] >= 1
    logged = journal.latest(20, kinds=("climo",))
    assert any(e["event"] == "calms" for e in logged)


def test_lot_f2_sci_once_and_wx_stop_enriched(client, monkeypatch):
    """Station à 6 nm une seule fois ; wx durée/max/level ; stop + tourisme cache."""
    import ici_engine
    import ici_warm
    import pearl_store
    from ici_engine import thin_cache_key
    from escale_api import escale_key
    from voyage_clock import sample_clock_at_time

    ici_engine.reset_caches()
    now = T0 + timedelta(days=40)
    _freeze(monkeypatch, now)
    client.put("/voyage/official", json=_official())
    voy = voyage_store.load_voyage(OFFICIAL_VOYAGE_ID)
    pearls = ici_warm.sample_route_nm(voy["points"])
    station = {"name": "PIRATA", "id": "pirata-1", "nm": 6.0, "lat": 14.8, "lon": -50.1, "url": "https://www.pmel.noaa.gov/pirata/"}
    for i, p in enumerate(pearls[:8]):
        ici_engine.thin_cache_put(thin_cache_key(p["lat"], p["lon"], 30.0), {
            "zee": None, "amp": [], "poe": [],
            "science": {"nearby": [station]},
            "sources": {"bi": "ok"},
        })
    events = ici_warm.route_events_from_pearls(voy["points"])
    scis = [e for e in events if e["kind"] == "sci"]
    assert len(scis) == 1 and scis[0]["facts"]["nm"] == 6.0 and scis[0]["name"] == "PIRATA"
    assert scis[0]["title"]["en"] == "Station passed"
    assert journal.tick(voy, now, force=True)["routeEvents"] == 1
    assert journal.tick(voy, now + timedelta(hours=1), force=True)["routeEvents"] == 0

    # wx : un épisode de mer forte durable + max, et un coup de vent.
    assert journal.wx_entry_from_grib({"id": "grib:quiet", "t": "2026-05-20T06:00:00Z", "windKnots": 12, "hs": 1.0}) is None
    gale = journal.wx_entry_from_grib({"id": "grib:c2", "t": "2026-05-21T06:00:00Z", "windKnots": 36.5, "dirFromDeg": 250, "hs": 2.0, "model": "GFS"})
    assert gale["event"] == "gale" and gale["hours"] == 6 and gale["maxWindKnots"] == 36.5
    run = journal.wx_events_from_gribs([
        {"id": "grib:s1", "t": "2026-06-01T00:00:00Z", "windKnots": 18, "hs": 2.6, "lat": 20, "lon": -30},
        {"id": "grib:s2", "t": "2026-06-01T06:00:00Z", "windKnots": 22, "hs": 4.2, "lat": 20, "lon": -31},
    ])
    assert len(run) == 1
    assert run[0]["hours"] == 6 and run[0]["maxHs"] == 4.2 and run[0]["level"] == "très forte"
    assert run[0]["facts"]["maxHs"] == 4.2 and run[0]["title"]["fr"]
    journal._append([
        {"id": "grib:s1", "kind": "grib", "t": "2026-06-01T00:00:00Z", "windKnots": 18, "hs": 2.6},
        {"id": "grib:s2", "kind": "grib", "t": "2026-06-01T06:00:00Z", "windKnots": 22, "hs": 4.2},
    ])
    assert journal.record_wx(now) == 1
    assert journal.record_wx(now) == 0

    # stop : jours à quai + 2 lieux si la fiche tourisme est en cache.
    marks = voy["clock"]["marks"]
    last = marks[-1]
    arrival = T0 + timedelta(hours=float(last["tHours"]))
    sample = sample_clock_at_time(voy["clock"], arrival)
    pearl_store.kv_put("escale", escale_key(last["name"], sample["lat"], sample["lon"], "fr"), {
        "sections": {"tourism": {"sights": [
            {"name": "Fort Saint-Louis", "nm": 0.4, "lat": 14.60, "lon": -61.07},
            {"name": "Bibliothèque Schoelcher", "nm": 0.8, "lat": 14.60, "lon": -61.07},
        ]}},
    })
    journal.reset()
    assert journal.record_stops(voy["clock"], arrival + timedelta(hours=1)) >= 1
    stop = next(e for e in journal.latest(10, kinds=("stop",)) if e["event"] == "arrival" and e["name"].startswith("Fort-de-France"))
    if isinstance(last.get("holdHours"), (int, float)) and last["holdHours"] > 0:
        assert stop["daysAtQuay"] == int(round(float(last["holdHours"]) / 24))
    assert stop["sights"] == ["Fort Saint-Louis", "Bibliothèque Schoelcher"]
    assert stop["facts"]["sights"][0] == "Fort Saint-Louis"
    assert stop["lat"] is not None and stop["entity"]["kind"] == "escale"

    body = client.get("/voyage/official/journal?limit=50&kinds=climo,sci", headers=PUBLIC).json()
    assert "climo" in body["kinds"] and "sci" in body["kinds"]
    assert {e["kind"] for e in body["latest"]} <= {"climo", "sci"}
    # After reset + stops only, latest filtered may be empty; kinds list still advertises them.
    assert body["voyageId"]
