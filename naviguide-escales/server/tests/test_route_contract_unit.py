"""Unit tests for route_contract.py"""
import pytest
from route_contract import in_passage_box, line_strings, iter_vertices, PANAMA_BOX, SUEZ_BOX


class TestInPassageBox:
    def test_panama_box_edges_inclusive(self):
        lon_min, lat_min, lon_max, lat_max = PANAMA_BOX
        assert in_passage_box(lon_min, lat_min, PANAMA_BOX) is True
        assert in_passage_box(lon_max, lat_max, PANAMA_BOX) is True
        assert in_passage_box(lon_min, lat_max, PANAMA_BOX) is True
        assert in_passage_box(lon_max, lat_min, PANAMA_BOX) is True

    def test_suez_box_edges_inclusive(self):
        lon_min, lat_min, lon_max, lat_max = SUEZ_BOX
        assert in_passage_box(lon_min, lat_min, SUEZ_BOX) is True
        assert in_passage_box(lon_max, lat_max, SUEZ_BOX) is True
        assert in_passage_box(lon_min, lat_max, SUEZ_BOX) is True
        assert in_passage_box(lon_max, lat_min, SUEZ_BOX) is True

    def test_panama_box_inside(self):
        assert in_passage_box(-80.0, 9.0, PANAMA_BOX) is True

    def test_suez_box_inside(self):
        assert in_passage_box(32.3, 30.5, SUEZ_BOX) is True

    def test_panama_box_outside_west(self):
        assert in_passage_box(-82.0, 9.0, PANAMA_BOX) is False

    def test_panama_box_outside_east(self):
        assert in_passage_box(-78.0, 9.0, PANAMA_BOX) is False

    def test_panama_box_outside_south(self):
        assert in_passage_box(-80.0, 8.0, PANAMA_BOX) is False

    def test_panama_box_outside_north(self):
        assert in_passage_box(-80.0, 10.0, PANAMA_BOX) is False

    def test_suez_box_outside_west(self):
        assert in_passage_box(31.9, 30.5, SUEZ_BOX) is False

    def test_suez_box_outside_east(self):
        assert in_passage_box(32.8, 30.5, SUEZ_BOX) is False

    def test_suez_box_outside_south(self):
        assert in_passage_box(32.3, 29.6, SUEZ_BOX) is False

    def test_suez_box_outside_north(self):
        assert in_passage_box(32.3, 31.6, SUEZ_BOX) is False


class TestLineStrings:
    def test_line_string_basic(self):
        fc = {
            "features": [
                {
                    "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                    "properties": {"from": "A", "to": "B", "type": "leg"},
                }
            ]
        }
        result = line_strings(fc)
        assert len(result) == 1
        assert result[0] == {
            "from": "A",
            "to": "B",
            "type": "leg",
            "coordinates": [[0, 0], [1, 1]],
        }

    def test_skips_point_features(self):
        fc = {
            "features": [
                {"geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {"name": "Port"}},
                {
                    "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                    "properties": {"from": "A", "to": "B", "type": "leg"},
                },
            ]
        }
        result = line_strings(fc)
        assert len(result) == 1
        assert result[0]["from"] == "A"

    def test_missing_properties_defaults_to_empty_string(self):
        fc = {
            "features": [
                {
                    "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                    "properties": {},
                }
            ]
        }
        result = line_strings(fc)
        assert len(result) == 1
        assert result[0]["from"] == ""
        assert result[0]["to"] == ""
        assert result[0]["type"] == ""

    def test_none_properties_defaults_to_empty_string(self):
        fc = {
            "features": [
                {
                    "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                    "properties": None,
                }
            ]
        }
        result = line_strings(fc)
        assert len(result) == 1
        assert result[0]["from"] == ""
        assert result[0]["to"] == ""
        assert result[0]["type"] == ""

    def test_none_feature_skipped(self):
        fc = {
            "features": [
                None,
                {
                    "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                    "properties": {"from": "A", "to": "B", "type": "leg"},
                },
            ]
        }
        result = line_strings(fc)
        assert len(result) == 1
        assert result[0]["from"] == "A"

    def test_missing_features_key_returns_empty_list(self):
        fc = {}
        result = line_strings(fc)
        assert result == []

    def test_none_features_returns_empty_list(self):
        fc = {"features": None}
        result = line_strings(fc)
        assert result == []

    def test_multiple_line_strings(self):
        fc = {
            "features": [
                {
                    "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                    "properties": {"from": "A", "to": "B", "type": "leg1"},
                },
                {
                    "geometry": {"type": "LineString", "coordinates": [[1, 1], [2, 2]]},
                    "properties": {"from": "B", "to": "C", "type": "leg2"},
                },
            ]
        }
        result = line_strings(fc)
        assert len(result) == 2
        assert result[0]["from"] == "A"
        assert result[1]["from"] == "B"


class TestIterVertices:
    def test_point_geometry(self):
        fc = {"features": [{"geometry": {"type": "Point", "coordinates": [10, 20]}}]}
        vertices = list(iter_vertices(fc))
        assert vertices == [(10.0, 20.0)]

    def test_line_string_geometry(self):
        fc = {"features": [{"geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1], [2, 2]]}}]}
        vertices = list(iter_vertices(fc))
        assert vertices == [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)]

    def test_multi_line_string_geometry(self):
        fc = {
            "features": [
                {"geometry": {"type": "MultiLineString", "coordinates": [[[0, 0], [1, 1]], [[2, 2], [3, 3]]]}}
            ]
        }
        vertices = list(iter_vertices(fc))
        assert vertices == [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0), (3.0, 3.0)]

    def test_mixed_geometries(self):
        fc = {
            "features": [
                {"geometry": {"type": "Point", "coordinates": [0, 0]}},
                {"geometry": {"type": "LineString", "coordinates": [[1, 1], [2, 2]]}},
                {"geometry": {"type": "MultiLineString", "coordinates": [[[3, 3], [4, 4]]]}},
            ]
        }
        vertices = list(iter_vertices(fc))
        assert vertices == [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0), (3.0, 3.0), (4.0, 4.0)]

    def test_polygon_raises_value_error(self):
        fc = {"features": [{"geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}}]}
        with pytest.raises(ValueError, match="géométrie inattendue"):
            list(iter_vertices(fc))

    def test_empty_feature_collection(self):
        fc = {"features": []}
        vertices = list(iter_vertices(fc))
        assert vertices == []

    def test_none_features(self):
        fc = {"features": None}
        vertices = list(iter_vertices(fc))
        assert vertices == []

    def test_missing_features_key(self):
        fc = {}
        vertices = list(iter_vertices(fc))
        assert vertices == []

    def test_none_feature_in_list(self):
        fc = {"features": [None, {"geometry": {"type": "Point", "coordinates": [1, 2]}}]}
        # A None feature has no geometry type: the contract refuses it loudly.
        with pytest.raises(ValueError):
            list(iter_vertices(fc))

    def test_none_geometry(self):
        fc = {"features": [{"geometry": None}]}
        with pytest.raises(ValueError):
            list(iter_vertices(fc))

    def test_none_coordinates(self):
        fc = {"features": [{"geometry": {"type": "LineString", "coordinates": None}}]}
        vertices = list(iter_vertices(fc))
        assert vertices == []