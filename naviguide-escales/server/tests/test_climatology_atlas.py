import threading
import time

import climatology_atlas
from climatology_atlas import (
    atlas_wind_at,
    atlas_wind_cached,
    climatology_block,
    corridor_cells,
    prefetch_atlas_cells,
    reset_atlas_cache,
    rose_speed_percentiles,
    wind_from_point,
)
from climatology_zones import zone_wind_at


def _payload(speed=16.2, direction=55):
    return {
        "kind": "climatology",
        "period": "1980-2020",
        "wind_atlas": {"most_likely": {"speed_knots": speed, "dir_deg": direction}},
    }


def test_atlas_wind_cached_never_touches_the_network(monkeypatch):
    reset_atlas_cache()

    def boom(*_a, **_k):
        raise AssertionError("network call from a hot loop")

    monkeypatch.setattr("climatology_atlas.fetch_atlas_point", boom)
    zone = zone_wind_at(15.0, -25.0, 6)
    w = atlas_wind_cached(15.0, -25.0, 6)
    assert w["source"] == "zone_fallback"
    assert w["kind"] == "climatology"
    assert w["speedKnots"] == zone["speedKnots"]

    # Once a cell is warmed (here through the network path), the cache answers.
    monkeypatch.setattr("climatology_atlas.fetch_atlas_point", lambda *a, **k: _payload())
    assert atlas_wind_at(15.0, -25.0, 6)["source"] == "atlas"
    monkeypatch.setattr("climatology_atlas.fetch_atlas_point", boom)
    assert atlas_wind_cached(15.1, -25.1, 6)["speedKnots"] == 16.2


def test_corridor_cells_pads_and_deduplicates():
    cells = corridor_cells([(46.15, -1.16), (46.2, -1.2)], [6, 7], pad=1)
    assert len(cells) == 9 * 2  # both points share the same 0.5° cell
    assert {m for _, _, m in cells} == {6, 7}
    lats = {la for la, _, _ in cells}
    assert lats == {45.5, 46.0, 46.5}
    assert corridor_cells([], [6]) == []


def test_prefetch_atlas_cells_respects_budget(monkeypatch):
    reset_atlas_cache()
    release = threading.Event()
    calls = []

    def slow(lat, lon, month, *a, **k):
        calls.append((lat, lon, month))
        release.wait(5)
        return _payload()

    monkeypatch.setattr("climatology_atlas.fetch_atlas_point", slow)
    cells = corridor_cells([(10.0, 20.0)], [6], pad=2)  # 25 cells, 8 workers
    started = time.monotonic()
    hits = prefetch_atlas_cells(cells, budget_s=0.3)
    elapsed = time.monotonic() - started
    release.set()
    assert elapsed < 2.0
    assert hits == 0
    # The loop keeps going without the network while the atlas is slow.
    assert atlas_wind_cached(10.0, 20.0, 6)["source"] == "zone_fallback"


def test_slow_atlas_answer_marks_it_dead(monkeypatch):
    reset_atlas_cache()
    monkeypatch.setattr(climatology_atlas, "SLOW_S", 0.0)
    monkeypatch.setattr("climatology_atlas._get_json", lambda *a, **k: _payload())
    assert climatology_atlas.fetch_atlas_point(15.0, -25.0, 6) is not None
    assert climatology_atlas.atlas_is_dead()
    reset_atlas_cache()


def test_wind_from_point_keeps_kind_and_doi():
    payload = {
        "kind": "climatology",
        "period": "1980-2020",
        "doi": {"wind": "10.48670/moi-00183"},
        "wind_atlas": {"most_likely": {"speed_knots": 16.2, "dir_deg": 55}},
        "wave": {"hs_p50_m": 1.4, "hs_p90_m": 2.8},
        "current": {"speed_knots": 0.4, "direction_to_deg": 270},
        "cyclone": {"nearby": 1, "crossings_if_leg": {"count": 2}},
    }
    w = wind_from_point(payload)
    assert w["kind"] == "climatology"
    assert w["source"] == "atlas"
    assert w["speedKnots"] == 16.2
    assert w["hsP90"] == 2.8
    assert w["currentKn"] == 0.4
    assert w["doi"]["wind"] == "10.48670/moi-00183"
    assert wind_from_point({"kind": "forecast"}) is None
    assert wind_from_point({"kind": "climatology"}) is None


def test_climatology_block_zone_if_api_dead(monkeypatch):
    reset_atlas_cache()

    def boom(*_a, **_k):
        return None

    monkeypatch.setattr("climatology_atlas.fetch_atlas_point", boom)
    monkeypatch.setattr("climatology_atlas.fetch_atlas_crossings", boom)
    block = climatology_block(15.0, -25.0, 6)
    assert block["kind"] == "climatology"
    assert block["source"] == "zone_fallback"
    zone = zone_wind_at(15.0, -25.0, 6)
    assert block["wind"]["speedKnots"] == zone["speedKnots"]
    assert block["point"] is None


def test_climatology_block_atlas_when_point_answers(monkeypatch):
    reset_atlas_cache()
    payload = {
        "kind": "climatology",
        "month": 6,
        "period": "1980-2020",
        "doi": {"wind": "10.48670/moi-00183"},
        "wind_atlas": {"most_likely": {"speed_knots": 16.2, "dir_deg": 55}},
        "wave": {"hs_p50_m": 1.4, "hs_p90_m": 2.8},
        "current": {"speed_knots": 0.4},
        "cyclone": {"nearby": 0},
    }

    monkeypatch.setattr("climatology_atlas.fetch_atlas_point", lambda *a, **k: payload)
    monkeypatch.setattr(
        "climatology_atlas.fetch_atlas_crossings",
        lambda *a, **k: {"count": 2, "kind": "climatology"},
    )
    block = climatology_block(15.0, -25.0, 6, dest_lat=14.6, dest_lon=-61.0)
    assert block["source"] == "atlas"
    assert block["point"]["wind_atlas"]["most_likely"]["speed_knots"] == 16.2
    assert block["crossings"]["count"] == 2
    assert block["point"]["wave"]["hs_p90_m"] == 2.8
    assert block["kind"] == "climatology"


def test_traces_are_not_atlas_empty_and_count_storms(monkeypatch):
    """Des traces IBTrACS ne donnent pas atlas_empty. Le compte est les tempêtes, pas les sommets."""
    reset_atlas_cache()
    payload = {
        "kind": "climatology",
        "period": "1980-2020",
        "cyclone": {
            "tracks_in_month": 99,
            "tracks": [
                {"sid": "A", "coordinates": [[170, -15], [179, -16], [-179, -17], [-170, -18]]},
                {"sid": "A", "coordinates": [[-160, -19], [-150, -20]]},
                {"sid": "B", "coordinates": [[10, 5], [11, 6], [12, 7]]},
            ],
        },
    }
    monkeypatch.setattr("climatology_atlas.fetch_atlas_point", lambda *a, **k: payload)
    monkeypatch.setattr("climatology_atlas.fetch_atlas_crossings", lambda *a, **k: None)
    block = climatology_block(15.0, -25.0, 9)
    assert block["status"] != "atlas_empty"
    assert block["source"] == "ibtracs"
    assert block["period"] == "1980-2020"
    assert block["ibtracsCount"] == 2
    assert block["kind"] == "climatology"


def test_census_counts_when_the_track_list_is_absent():
    from climatology_atlas import ibtracs_track_count
    assert ibtracs_track_count({"cyclone": {"tracks_in_month": 12}}) == 12
    assert ibtracs_track_count({"kind": "climatology"}) == 0
    assert ibtracs_track_count({"cyclone": {"nearby": 1}}) == 0


def test_c4_rose_speed_percentiles_from_sectors():
    rose = {
        "most_likely": {"speed_knots": 16.0, "dir_deg": 45},
        "directions_from": [
            {"dir_deg": 0, "pct": 25, "speed_knots": 8.0},
            {"dir_deg": 45, "pct": 50, "speed_knots": 16.0},
            {"dir_deg": 90, "pct": 25, "speed_knots": 22.0},
        ],
    }
    p25, p50, p75 = rose_speed_percentiles(rose)
    assert p25 <= p50 <= p75
    assert p25 == 8.0
    assert p50 == 16.0
    w = wind_from_point({
        "kind": "climatology",
        "wind_atlas": rose,
    })
    assert w["roseKnots"] == [p25, p50, p75]
    assert rose_speed_percentiles({"most_likely": {"speed_knots": 16}}) is None
