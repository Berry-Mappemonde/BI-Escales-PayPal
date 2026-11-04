"""La CI charge un extrait figé d'aires interdites, sans GET /amp/nogo.

Les items ont la forme de amp_nogo._item_from_feature. Un point est dedans
si amp_traffic.point_in_geom le dit. Une ligne synthétique qui traverse
North Chesterfield doit être vue. Sur public/route.geojson le test compte
les segments qui coupent l'extrait et l'écrit sur la sortie : le compte,
zéro ou non, ne fait pas échouer la CI.
"""
import json
from collections import Counter
from pathlib import Path

from amp_nogo import _item_from_feature
from amp_traffic import is_forbidden_pleasure, point_in_geom
from route_contract import line_strings

PIN = Path(__file__).resolve().parent / "fixtures" / "amp_nogo_pin.geojson"
ROUTE = Path(__file__).resolve().parents[2] / "public" / "route.geojson"

# Trait horizontal figé. Les bouts sont hors de North Chesterfield ;
# (158.18898, -19.82437) est sur le trait et dans le polygone.
_NC_A = (158.084, -19.82437)
_NC_B = (159.189, -19.82437)
_NC_INSIDE = (158.18898, -19.82437)

_PIN_CODES = {
    "AINCL81": ("North Chesterfield", 1, 1),
    "AINCL45": ("Yves Merlet", 1, 3),
    "AIIDN1055": ("Padang City Area Aquatic Park - Area II - Core Zone", 2, 1),
}


def _pin_features() -> list[dict]:
    data = json.loads(PIN.read_text())
    features = data.get("features") if isinstance(data, dict) else None
    assert isinstance(features, list)
    return features


def _pin_items() -> list[dict]:
    items = []
    for feat in _pin_features():
        item = _item_from_feature(feat)
        if item:
            items.append(item)
    return items


def _item(site_id: str) -> dict:
    found = [item for item in _pin_items() if item["id"] == site_id]
    assert len(found) == 1
    return found[0]


def _short_arc(lon1: float, lon2: float) -> tuple[float, float]:
    """Ramène le segment sur le court arc, sans traverser la carte en long."""
    if lon2 - lon1 > 180.0:
        lon2 -= 360.0
    elif lon1 - lon2 > 180.0:
        lon2 += 360.0
    return lon1, lon2


def _wrap(lon: float) -> float:
    return (lon + 180.0) % 360.0 - 180.0


def _clip_interval(lon1, lat1, lon2, lat2, box):
    """Paramètre t du segment qui rencontre la boîte, bords inclus."""
    t0, t1 = 0.0, 1.0
    for lo, hi, origin, delta in (
        (box[0], box[2], lon1, lon2 - lon1),
        (box[1], box[3], lat1, lat2 - lat1),
    ):
        if abs(delta) <= 1e-15:
            if origin < lo or origin > hi:
                return None
            continue
        enter = (lo - origin) / delta
        leave = (hi - origin) / delta
        if enter > leave:
            enter, leave = leave, enter
        t0 = max(t0, enter)
        t1 = min(t1, leave)
        if t0 > t1:
            return None
    return t0, t1


def _segment_hits(lon1, lat1, lon2, lat2, item) -> bool:
    """Vrai si un échantillon du court arc tombe dans l'item, via point_in_geom."""
    lon1, lon2 = _short_arc(float(lon1), float(lon2))
    lat1, lat2 = float(lat1), float(lat2)
    clipped = _clip_interval(lon1, lat1, lon2, lat2, item["bbox"])
    if clipped is None:
        return False
    t0, t1 = clipped
    span = max(item["bbox"][2] - item["bbox"][0], item["bbox"][3] - item["bbox"][1], 1e-6)
    step = min(0.005, span / 8.0)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    length = max(abs(dlon) * (t1 - t0), abs(dlat) * (t1 - t0))
    n = min(int(length / step) + 1, 2000)
    geom = item["geom"]
    for k in range(n + 1):
        t = t0 + (t1 - t0) * (k / n)
        lon = _wrap(lon1 + dlon * t)
        lat = lat1 + dlat * t
        if point_in_geom(lon, lat, geom):
            return True
    return False


def test_pin_extract_builds_forbidden_items_without_network(monkeypatch):
    def _refuse(*_args, **_kwargs):
        raise AssertionError("GET /amp/nogo")

    monkeypatch.setattr("amp_nogo.httpx.get", _refuse)
    raw = PIN.read_text()
    assert "http" not in raw
    features = _pin_features()
    assert len(features) == 3
    assert [feat["id"] for feat in features] == list(_PIN_CODES)
    items = _pin_items()
    assert len(items) == 3
    for feat, item in zip(features, items):
        props = feat["properties"]
        name, entry, speed = _PIN_CODES[feat["id"]]
        assert props["name"] == name
        assert props["entry"] == entry
        assert props["speed"] == speed
        assert is_forbidden_pleasure(entry, speed) is True
        assert item["id"] == feat["id"]
        assert item["name"] == name
        assert set(item) == {"id", "geom", "bbox", "name"}
        assert item["geom"]["type"] in ("Polygon", "MultiPolygon")
        assert item["bbox"] is not None


def test_regulated_codes_are_not_forbidden_items():
    """entry 2 et speed 2 : régulé. Le même polygone ne devient pas un item.

    Padang reste un item : speed 1 interdit la plaisance même si entry vaut 2.
    """
    assert is_forbidden_pleasure(2, 2) is False
    feat = json.loads(json.dumps(
        next(f for f in _pin_features() if f["id"] == "AINCL81")
    ))
    feat["properties"]["entry"] = 2
    feat["properties"]["speed"] = 2
    assert _item_from_feature(feat) is None
    padang = _item("AIIDN1055")
    assert padang["name"] == _PIN_CODES["AIIDN1055"][0]
    assert is_forbidden_pleasure(2, 1) is True


def test_synthetic_crossing_of_north_chesterfield_is_detected():
    nc = _item("AINCL81")
    assert point_in_geom(_NC_A[0], _NC_A[1], nc["geom"]) is False
    assert point_in_geom(_NC_B[0], _NC_B[1], nc["geom"]) is False
    assert point_in_geom(_NC_INSIDE[0], _NC_INSIDE[1], nc["geom"]) is True
    assert _segment_hits(_NC_A[0], _NC_A[1], _NC_B[0], _NC_B[1], nc) is True
    for site_id in ("AINCL45", "AIIDN1055"):
        assert _segment_hits(_NC_A[0], _NC_A[1], _NC_B[0], _NC_B[1], _item(site_id)) is False


def test_dateline_jump_does_not_count_as_north_chesterfield():
    nc = _item("AINCL81")
    assert _segment_hits(170.0, -19.3, -170.0, -19.3, nc) is False


def test_public_route_hit_count_is_printed_and_not_required():
    """Le compte est affiché. Il n'est pas comparé à zéro."""
    items = _pin_items()
    assert len(items) == 3
    lines = line_strings(json.loads(ROUTE.read_text()))
    assert lines
    hits = []
    examined = 0
    for line in lines:
        coords = line["coordinates"]
        for index in range(len(coords) - 1):
            start, end = coords[index], coords[index + 1]
            if not start or not end or len(start) < 2 or len(end) < 2:
                continue
            examined += 1
            matched = [
                item
                for item in items
                if _segment_hits(start[0], start[1], end[0], end[1], item)
            ]
            if matched:
                hits.append({
                    "from": line["from"],
                    "to": line["to"],
                    "ids": [item["id"] for item in matched],
                })
    assert examined > 0
    print(f"AMP_PIN_HITS {len(hits)}")
    for item in items:
        count = sum(1 for hit in hits if item["id"] in hit["ids"])
        print(f"AMP_PIN_AREA {item['id']} {count} {item['name']}")
    legs = Counter((hit["from"], hit["to"]) for hit in hits)
    for (src, dst), count in sorted(legs.items(), key=lambda row: (-row[1], row[0])):
        print(f"AMP_PIN_LEG {count} {src} → {dst}")
    # Bloquant : aucune traversée de réserve sur la route publiée
    assert len(hits) == 0, f"La route publiée traverse {len(hits)} segment(s) d'aire(s) interdite(s)"
