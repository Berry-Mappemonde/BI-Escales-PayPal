"""Contrat du module unique des longitudes (server/longitude.py)."""
from __future__ import annotations

import math

import pytest

from longitude import (
    delta_lon,
    interp_lon_shortest,
    lon_east_of,
    unwrap_lon,
    wrap_lon,
    wrap_lon_into,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        (0.0, 0.0),
        (179.85, 179.85),
        (180.0, 180.0),
        (-180.0, -180.0),
        (181.0, -179.0),
        (-181.0, 179.0),
        (236.84, 236.84 - 360.0),
        (-314.0, 46.0),
        (540.0, 180.0),
        (-540.0, -180.0),
        (725.5, 5.5),
        (-1085.0, -5.0),
    ],
)
def test_wrap_lon(raw, expected):
    assert wrap_lon(raw) == pytest.approx(expected, abs=1e-9)
    assert -180.0 <= wrap_lon(raw) <= 180.0


def test_wrap_lon_keeps_in_range_values_bit_for_bit():
    for x in (0.1, -0.1, 166.4567891234, -176.123456789, 179.999999999):
        assert wrap_lon(x) == x


def test_wrap_lon_non_finite_does_not_loop():
    assert math.isnan(wrap_lon(float("nan")))
    assert wrap_lon(float("inf")) == float("inf")
    assert wrap_lon(float("-inf")) == float("-inf")


def test_wrap_lon_huge_values_terminate():
    assert -180.0 <= wrap_lon(1e12 + 0.5) <= 180.0


def test_unwrap_lon_picks_nearest_copy():
    assert unwrap_lon(179.0, -179.0) == 181.0
    assert unwrap_lon(-179.0, 179.0) == -181.0
    assert unwrap_lon(-186.0, 166.0) == -194.0
    assert unwrap_lon(10.0, 20.0) == 20.0
    assert unwrap_lon(None, 200.0) == 200.0
    assert math.isnan(unwrap_lon(10.0, float("nan")))
    assert unwrap_lon(float("nan"), 200.0) == 200.0
    assert abs(unwrap_lon(0.0, 1e9) - 0.0) <= 180.0


def test_delta_lon_is_shortest_signed_arc():
    assert delta_lon(-180.0, 179.85) == pytest.approx(-0.15)
    assert delta_lon(179.0, -179.0) == pytest.approx(2.0)
    assert delta_lon(-176.0, 166.0) == pytest.approx(-18.0)
    assert delta_lon(10.0, 20.0) == 10.0
    assert delta_lon(0.0, 180.0) == 180.0


def test_interp_lon_shortest_crosses_antimeridian_without_crossing_globe():
    # Mata-Utu (-176) → Nouméa (+166) : 18° vers l'ouest, pas 342° vers l'est.
    mid = interp_lon_shortest(-176.0, 166.0, 0.5)
    assert mid == pytest.approx(175.0)
    for k in range(0, 11):
        lon = interp_lon_shortest(-180.0, 179.85, k / 10)
        assert -180.0 <= lon <= 180.0
        assert abs(delta_lon(-180.0, lon)) <= 0.15 + 1e-9
    assert interp_lon_shortest(-185.0, -193.0, 0.5) == pytest.approx(171.0)
    assert interp_lon_shortest(10.0, 20.0, 0.25) == 12.5
    assert interp_lon_shortest(10.0, 20.0, 0.0) == 10.0
    assert interp_lon_shortest(10.0, 20.0, 1.0) == 20.0


def test_wrap_lon_into_hycom_range():
    assert wrap_lon_into(-10.0, 74.0) == 350.0
    assert wrap_lon_into(74.0, 74.0) == 74.0
    assert wrap_lon_into(434.0, 74.0) == 74.0
    assert wrap_lon_into(100.0, 74.0) == 100.0


def test_lon_east_of():
    assert lon_east_of(-170.0, 170.0) == 190.0
    assert lon_east_of(175.0, 170.0) == 175.0
    assert lon_east_of(180.0, -180.0) == 180.0
    assert lon_east_of(-180.0, -180.0) == -180.0
