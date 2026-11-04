"""Couloirs cargos et score anti-trafic (repris de test_routing_ab_metrics)."""

from copy import deepcopy

from shipping_lanes import (
    anti_shipping_at,
    anti_shipping_of,
    anti_shipping_score,
    attach_anti_shipping,
    lane_hits,
)


def test_anti_shipping_quiet_vs_busy():
    quiet = [[-30.0, 0.0], [-35.0, 2.0]]
    busy = [[0.5, 51.0], [1.0, 51.2]]  # Pas-de-Calais
    assert anti_shipping_score(quiet) > anti_shipping_score(busy)
    assert anti_shipping_score(quiet) == 1.0
    assert anti_shipping_score([]) == 1.0


def test_named_berry_corridors():
    gibraltar = [[-5.5, 36.0], [-5.8, 36.1]]
    aden = [[48.0, 13.0], [52.0, 13.2]]
    malacca = [[101.0, 3.0], [104.0, 4.0]]
    assert "Gibraltar" in lane_hits(gibraltar)
    assert "Gulf of Aden" in lane_hits(aden)
    assert "Malacca" in lane_hits(malacca)
    assert anti_shipping_score(gibraltar) < 1
    assert anti_shipping_score(aden) < 1
    assert anti_shipping_score(malacca) < 1


def test_anti_shipping_at_exposes_r10a_pack():
    pack = anti_shipping_at(36.0, -5.5)
    assert pack is not None
    assert "Gibraltar" in pack["lanes"]
    assert 0.0 <= pack["score"] < 1.0
    assert anti_shipping_at(0.0, -30.0) is None


def test_attach_does_not_move_geometry():
    coords = [[-5.5, 36.0], [-5.8, 36.1], [-6.0, 35.9]]
    route = {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": deepcopy(coords)},
        "properties": {"role": "searoute-leg"},
    }
    before = deepcopy(route["geometry"]["coordinates"])
    out = attach_anti_shipping(route)
    assert out["geometry"]["coordinates"] == before
    pack = out["properties"]["antiShipping"]
    assert pack == anti_shipping_of(coords)
    assert "Gibraltar" in pack["lanes"]
    assert pack["score"] < 1
    assert out["properties"]["role"] == "searoute-leg"
