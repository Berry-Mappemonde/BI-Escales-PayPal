from pathlib import Path

import pytest

from polar_engine import parse_polar_csv


CSV = Path(__file__).resolve().parents[1].parent / "public" / "Leopard46_Standard_Sails.csv"


@pytest.fixture(scope="module")
def polar():
    return parse_polar_csv(CSV.read_bytes(), boat_name="Leopard 46")


def test_parse_leopard(polar):
    assert polar.boat_name == "Leopard 46"
    assert polar.speed(90, 12) > 0


def test_summary_has_vmg(polar):
    s = polar.summary()
    assert "upwind" in s[12]
    assert "downwind" in s[12]


def test_full_grid_shape(polar):
    assert polar.generate_full_grid().shape == (181, 61)


def test_twa_zero_is_zero(polar):
    assert polar.speed(0, 12) == 0
