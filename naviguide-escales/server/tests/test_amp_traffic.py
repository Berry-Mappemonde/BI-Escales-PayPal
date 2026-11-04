from amp_traffic import (
    geom_bbox,
    is_forbidden_pleasure,
    point_in_geom,
    traffic_kind,
)

SQUARE = {
    "type": "Polygon",
    "coordinates": [[
        [-1.2, 46.1], [-1.0, 46.1], [-1.0, 46.2], [-1.2, 46.2], [-1.2, 46.1],
    ]],
}


def test_traffic_kind_codes():
    assert traffic_kind(1, 3) == "forbidden"
    assert traffic_kind(3, 1) == "forbidden"
    assert traffic_kind(2, 3) == "regulated"
    assert traffic_kind(3, 2) == "regulated"
    assert traffic_kind(0, 3) == "allowed"
    assert traffic_kind(3, 3) == "unknown"
    assert traffic_kind(None, None) == "unknown"
    assert is_forbidden_pleasure(1, 0) is True
    assert is_forbidden_pleasure(0, 3) is False


def test_point_in_geom_and_bbox():
    assert point_in_geom(-1.1, 46.15, SQUARE) is True
    assert point_in_geom(-1.5, 46.15, SQUARE) is False
    box = geom_bbox(SQUARE)
    assert box[0] == -1.2 and box[2] == -1.0
    assert box[1] == 46.1 and box[3] == 46.2
