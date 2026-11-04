"""La route Berry du fichier ne traverse pas la terre.

Le fichier est le résultat du routeur. L'application le charge : la route
Berry ne se recalcule pas à chaque ouverture. Seule la jambe terrestre
Saint-Maur → La Rochelle a le droit de toucher la terre.

L'échantillonneur (segment_crosses_land) reste. L'oracle shapely s'y ajoute :
intersection du segment avec les polygones Natural Earth déjà chargés par
le moteur. Les boîtes Panama et Suez sont des passages, elles sont retirées
de l'intersection. Un recouvrement d'au plus 20 km collé à une extrémité
reste une approche (même garde-fou que le moteur) ; au-delà, ou à plus de
20 km des deux bouts, c'est une traversée.
"""
import gzip
import json
from pathlib import Path

from geographiclib.geodesic import Geodesic
from shapely.geometry import LineString, box as shapely_box
from shapely.ops import unary_union
from shapely.strtree import STRtree

from route_contract import PANAMA_BOX, SUEZ_BOX
from route_engine import _NE_TREE, segment_crosses_land, split_antimeridian

ROUTE = Path(__file__).resolve().parents[2] / "public" / "route.geojson"
# Même produit que route_engine._load_ne_land_tree (Natural Earth 1:10m),
# allégé, pour la CI où le shapefile et pyshp ne sont pas là.
_LAND_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ne_10m_land_oracle.json.gz"
# route_engine._segment_crosses_land : ≤ 20 km avec un bout à terre n'est pas une traversée.
ENGINE_SHORT_LAND_M = 20_000.0

_GEOD = Geodesic.WGS84
_POLYGONS: list | None = None
_TREE: STRtree | None = None


def test_official_route_avoids_land():
    fc = json.loads(ROUTE.read_text())
    assert len(fc["features"]) == 72
    wallis = [
        f for f in fc["features"]
        if "Wallis" in (f.get("properties") or {}).get("from", "")
        and "Nouméa" in (f.get("properties") or {}).get("to", "")
    ]
    assert len(wallis) == 2
    hits = []
    maritime = 0
    for feature in fc["features"]:
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        if geom.get("type") != "LineString":
            continue
        if props.get("type") == "overland":
            assert props.get("from", "").startswith("Saint-Maur")
            assert len(geom["coordinates"]) == 2
            continue
        assert props.get("type") == "maritime"
        maritime += 1
        coords = geom["coordinates"]
        for i in range(len(coords) - 1):
            a, b = coords[i], coords[i + 1]
            if segment_crosses_land(a[0], a[1], b[0], b[1]):
                hits.append((props.get("from"), props.get("to"), a, b))
    assert maritime == 35
    assert hits == []


def _land_index() -> tuple[list, STRtree]:
    """Polygones Natural Earth : ceux du moteur s'il les a chargés, sinon l'extrait."""
    global _POLYGONS, _TREE
    if _TREE is not None and _POLYGONS is not None:
        return _POLYGONS, _TREE
    if _NE_TREE is not None:
        polygons = [geom for geom in _NE_TREE.geometries if geom is not None and not geom.is_empty]
    else:
        raw = json.loads(gzip.decompress(_LAND_FIXTURE.read_bytes()))
        polygons = []
        for feature in raw.get("features") or []:
            geom = feature.get("geometry") or {}
            if geom.get("type") != "Polygon":
                continue
            poly = _polygon_from_geojson(geom)
            if poly is not None and not poly.is_empty:
                polygons.append(poly)
    assert polygons, "aucun polygone Natural Earth"
    _POLYGONS = polygons
    _TREE = STRtree(polygons)
    return _POLYGONS, _TREE


def _polygon_from_geojson(geom: dict):
    from shapely.geometry import shape

    poly = shape(geom)
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly


def _passage_boxes():
    return (
        shapely_box(PANAMA_BOX[0], PANAMA_BOX[1], PANAMA_BOX[2], PANAMA_BOX[3]),
        shapely_box(SUEZ_BOX[0], SUEZ_BOX[1], SUEZ_BOX[2], SUEZ_BOX[3]),
    )


def _segment_lines(lon1: float, lat1: float, lon2: float, lat2: float) -> list[LineString]:
    lines = []
    for lon_a, lat_a, lon_b, lat_b in split_antimeridian(lon1, lat1, lon2, lat2):
        line = LineString([(lon_a, lat_a), (lon_b, lat_b)])
        if line.length:
            lines.append(line)
    return lines


def _land_overlap(lon1: float, lat1: float, lon2: float, lat2: float, *, exempt_passages: bool):
    polygons, tree = _land_index()
    pieces = []
    for line in _segment_lines(lon1, lat1, lon2, lat2):
        for index in tree.query(line, predicate="intersects"):
            hit = line.intersection(polygons[int(index)])
            if not hit.is_empty:
                pieces.append(hit)
    if not pieces:
        return LineString()
    overlap = unary_union(pieces)
    if exempt_passages:
        for passage in _passage_boxes():
            overlap = overlap.difference(passage)
    return overlap


def _length_m(geom) -> float:
    if geom is None or geom.is_empty:
        return 0.0
    if geom.geom_type == "LineString":
        coords = list(geom.coords)
    elif geom.geom_type == "MultiLineString":
        return sum(_length_m(part) for part in geom.geoms)
    elif geom.geom_type == "GeometryCollection":
        return sum(_length_m(part) for part in geom.geoms)
    else:
        return 0.0
    total = 0.0
    for start, end in zip(coords, coords[1:]):
        total += _GEOD.Inverse(start[1], start[0], end[1], end[0])["s12"]
    return total


def _samples(geom):
    if geom is None or geom.is_empty:
        return
    if geom.geom_type == "Point":
        yield geom.x, geom.y
        return
    if geom.geom_type == "LineString":
        count = max(1, int(geom.length / 0.02))
        for step in range(count + 1):
            point = geom.interpolate(step / count, normalized=True)
            yield point.x, point.y
        return
    if geom.geom_type in ("MultiLineString", "MultiPoint", "GeometryCollection"):
        for part in geom.geoms:
            yield from _samples(part)


def _away_from_both_ends(geom, lon1: float, lat1: float, lon2: float, lat2: float) -> bool:
    for lon, lat in _samples(geom):
        to_start = _GEOD.Inverse(lat, lon, lat1, lon1)["s12"]
        to_end = _GEOD.Inverse(lat, lon, lat2, lon2)["s12"]
        if to_start > ENGINE_SHORT_LAND_M and to_end > ENGINE_SHORT_LAND_M:
            return True
    return False


def _crosses_land(lon1: float, lat1: float, lon2: float, lat2: float) -> bool:
    overlap = _land_overlap(lon1, lat1, lon2, lat2, exempt_passages=True)
    if overlap.is_empty:
        return False
    if _length_m(overlap) > ENGINE_SHORT_LAND_M:
        return True
    return _away_from_both_ends(overlap, lon1, lat1, lon2, lat2)


def _line_features(fc: dict, kind: str | None = None) -> list[dict]:
    rows = []
    for feature in fc["features"]:
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        if geom.get("type") != "LineString":
            continue
        if kind is not None and props.get("type") != kind:
            continue
        rows.append(feature)
    return rows


def test_shapely_oracle_allows_panama_and_rejects_other_land():
    """Panama reste un passage : le segment y touche la terre, hors de la boîte non."""
    fc = json.loads(ROUTE.read_text())
    suez = shapely_box(SUEZ_BOX[0], SUEZ_BOX[1], SUEZ_BOX[2], SUEZ_BOX[3])
    panama_land_m = 0.0
    crossings = []
    for feature in _line_features(fc, "maritime"):
        props = feature.get("properties") or {}
        coords = feature["geometry"]["coordinates"]
        for index in range(len(coords) - 1):
            lon1, lat1 = float(coords[index][0]), float(coords[index][1])
            lon2, lat2 = float(coords[index + 1][0]), float(coords[index + 1][1])
            raw = _land_overlap(lon1, lat1, lon2, lat2, exempt_passages=False)
            if not raw.is_empty and raw.intersects(suez):
                crossings.append(("suez", props.get("from"), props.get("to"), index))
            if _crosses_land(lon1, lat1, lon2, lat2):
                crossings.append((props.get("from"), props.get("to"), index, round(_length_m(raw))))
            if "Cayenne" in (props.get("from") or "") and "Papeete" in (props.get("to") or ""):
                exempted = _land_overlap(lon1, lat1, lon2, lat2, exempt_passages=True)
                if _length_m(raw) > ENGINE_SHORT_LAND_M and exempted.is_empty:
                    panama_land_m = max(panama_land_m, _length_m(raw))
    assert crossings == []
    assert panama_land_m > ENGINE_SHORT_LAND_M


def test_shapely_oracle_flags_inland_and_keeps_saint_maur_on_land():
    assert _crosses_land(-9.0, 40.0, -1.0, 40.0)
    assert _crosses_land(-1.6, 47.2, -1.15, 47.2)
    fc = json.loads(ROUTE.read_text())
    overland = _line_features(fc, "overland")
    assert len(overland) == 1
    coords = overland[0]["geometry"]["coordinates"]
    overlap = _land_overlap(
        float(coords[0][0]), float(coords[0][1]),
        float(coords[1][0]), float(coords[1][1]),
        exempt_passages=False,
    )
    assert _length_m(overlap) > ENGINE_SHORT_LAND_M
