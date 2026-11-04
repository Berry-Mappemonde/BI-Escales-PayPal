"""Parité polaire Python (horloge = PolarData) sur 20 cas partagés."""
from __future__ import annotations

import json
from pathlib import Path

from polar_engine import PolarData
from voyage_clock import polar_boat_speed

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "polar_cases.json"


def _load():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_polar_fixture_has_twenty_cases():
    data = _load()
    assert len(data["cases"]) == 20
    assert data["tolerance_kn"] == 0.05
    assert data["polar"]["twa_rows"] and data["polar"]["tws_cols"]


def test_polar_parity_clock_matches_polar_data_and_fixture():
    data = _load()
    raw = data["polar"]
    engine = PolarData(raw["twa_rows"], raw["tws_cols"], raw["matrix"], boat_name="Leopard 46")
    tol = float(data["tolerance_kn"])
    for case in data["cases"]:
        twa, tws = case["twa"], case["tws"]
        expected = case["expected_kn"]
        clock = polar_boat_speed(raw, twa, tws)
        polar = engine.speed(twa, tws)
        assert clock is not None
        assert abs(clock - expected) <= tol, (twa, tws, clock, expected)
        assert abs(polar - expected) <= tol, (twa, tws, polar, expected)
        assert abs(clock - polar) <= tol, (twa, tws, clock, polar)


def test_polar_twa_port_starboard_symmetry():
    data = _load()
    raw = data["polar"]
    assert polar_boat_speed(raw, 90, 12) == polar_boat_speed(raw, -90, 12)
