"""Index spatial en mémoire et niveau de détail pour les catalogues GeoJSON.

Le serveur garde les sources brutes en cache; chaque réponse ne contient que
la fenêtre utile, avec un budget strict d'objets Leaflet à créer côté client.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from typing import Any, Iterable

from longitude import lon_east_of


GRID_CELL_DEG = 10.0
GRID_WIDTH = int(360 / GRID_CELL_DEG)
GRID_HEIGHT = int(180 / GRID_CELL_DEG)
MAX_RENDER_FEATURES = 420


@dataclass(frozen=True)
class Bbox:
    west: float
    south: float
    east: float
    north: float


@dataclass
class IndexedFeature:
    key: str
    feature: dict
    envelope: Bbox
    source: str



# Fields that describe one point only; a grouped cell must not carry them.
CLUSTER_POINT_ONLY_PROPS = frozenset({
    "name", "title", "description", "website", "telephone", "url", "canal_vhf",
    "source_urls", "manager_url", "visit_url", "country", "region", "funder",
    "wmo", "ship", "email",
})

def parse_bbox(raw: str | None) -> Bbox | None:
    """Parse une bbox Leaflet, y compris une fenêtre qui traverse ±180°."""
    if not raw:
        return None
    try:
        west, south, east, north = (float(value) for value in raw.split(","))
    except (TypeError, ValueError) as exc:
        raise ValueError("bbox invalide") from exc
    if not all(math.isfinite(value) for value in (west, south, east, north)):
        raise ValueError("bbox invalide")
    if south > north or south < -90 or north > 90 or west == east:
        raise ValueError("bbox invalide")
    return Bbox(west, south, east, north)


def science_source_of(properties: dict | None) -> str:
    props = properties or {}
    return str(
        props.get("source")
        or ("argo" if props.get("kind") == "argo_float" else "")
        or ("csr" if props.get("kind") == "cruise" else "")
    )


def _positions(value: Any) -> Iterable[tuple[float, float]]:
    if not isinstance(value, (list, tuple)):
        return
    if len(value) >= 2 and isinstance(value[0], (int, float)) and isinstance(value[1], (int, float)):
        lon, lat = float(value[0]), float(value[1])
        if math.isfinite(lon) and math.isfinite(lat):
            yield lon, lat
        return
    for child in value:
        yield from _positions(child)


def feature_envelope(feature: dict) -> Bbox | None:
    geometry = feature.get("geometry") or {}
    positions = list(_positions(geometry.get("coordinates")))
    if geometry.get("type") == "GeometryCollection":
        for member in geometry.get("geometries") or []:
            positions.extend(_positions((member or {}).get("coordinates")))
    if not positions:
        return None
    lons, lats = zip(*positions)
    return Bbox(min(lons), min(lats), max(lons), max(lats))


def _lon_ranges(west: float, east: float) -> list[tuple[float, float]]:
    if east >= west:
        return [(west, east)]
    return [(west, 180.0), (-180.0, east)]


def _intersects(a: Bbox, b: Bbox) -> bool:
    if a.north < b.south or a.south > b.north:
        return False
    if a.east - a.west >= 360:
        return True
    for west, east in _lon_ranges(b.west, b.east):
        for shift in (-360.0, 0.0, 360.0):
            if a.east + shift >= west and a.west + shift <= east:
                return True
    return False


def _x_cells(west: float, east: float) -> range:
    if east - west >= 360:
        return range(GRID_WIDTH)
    start = math.floor((west + 180.0) / GRID_CELL_DEG)
    end = math.floor((east + 180.0) / GRID_CELL_DEG)
    return range(start, end + 1)


def _grid_cells(bbox: Bbox) -> Iterable[tuple[int, int]]:
    south = max(-90.0, bbox.south)
    north = min(90.0, bbox.north)
    y_start = max(0, min(GRID_HEIGHT - 1, math.floor((south + 90.0) / GRID_CELL_DEG)))
    y_end = max(0, min(GRID_HEIGHT - 1, math.floor((north + 90.0) / GRID_CELL_DEG)))
    for west, east in _lon_ranges(bbox.west, bbox.east):
        for raw_x in _x_cells(west, east):
            for y in range(y_start, y_end + 1):
                yield raw_x % GRID_WIDTH, y


def _lod_budget(zoom: float, requested: int) -> int:
    cap = min(MAX_RENDER_FEATURES, max(1, int(requested)))
    if zoom <= 3:
        return min(cap, 80)
    if zoom <= 5:
        return min(cap, 150)
    if zoom <= 8:
        return min(cap, 280)
    return cap


def _vertex_budget(zoom: float) -> int:
    if zoom <= 3:
        return 64
    if zoom <= 6:
        return 128
    if zoom <= 9:
        return 256
    return 600


def _downsample_line(coords: list, budget: int, close_ring: bool = False) -> list:
    if len(coords) <= budget:
        return coords
    ring = close_ring and len(coords) > 3 and coords[0] == coords[-1]
    values = coords[:-1] if ring else coords
    if len(values) <= budget:
        result = values
    else:
        stride = max(1, math.ceil(len(values) / budget))
        result = values[::stride]
        if result[-1] != values[-1]:
            result.append(values[-1])
    if ring and result[0] != result[-1]:
        result.append(result[0])
    return result


def _simplify_coordinates(geometry_type: str, coordinates: Any, budget: int) -> Any:
    if geometry_type == "LineString":
        return _downsample_line(coordinates or [], budget)
    if geometry_type == "MultiLineString":
        return [_downsample_line(line or [], budget) for line in coordinates or []]
    if geometry_type == "Polygon":
        return [_downsample_line(ring or [], budget, close_ring=True) for ring in coordinates or []]
    if geometry_type == "MultiPolygon":
        return [
            [_downsample_line(ring or [], budget, close_ring=True) for ring in polygon or []]
            for polygon in coordinates or []
        ]
    return coordinates


def simplify_feature(feature: dict, zoom: float) -> dict:
    copied = deepcopy(feature)
    geometry = copied.get("geometry") or {}
    geometry_type = geometry.get("type")
    if geometry_type in {"LineString", "MultiLineString", "Polygon", "MultiPolygon"}:
        geometry["coordinates"] = _simplify_coordinates(
            geometry_type,
            geometry.get("coordinates"),
            _vertex_budget(zoom),
        )
    return copied


def _relative_lon(lon: float, west: float) -> float:
    return lon_east_of(lon, west)


def _cluster_points(points: list[dict], bbox: Bbox, budget: int, zoom: float, catalog: str) -> list[dict]:
    if len(points) <= budget:
        return [simplify_feature(feature, zoom) for feature in points]
    span_lon = bbox.east - bbox.west if bbox.east >= bbox.west else bbox.east + 360.0 - bbox.west
    span_lat = max(0.001, bbox.north - bbox.south)
    ratio = max(0.25, min(4.0, span_lon / span_lat))
    columns = max(1, int(math.sqrt(budget * ratio)))
    rows = max(1, math.ceil(budget / columns))
    scale = 1
    clusters: dict[tuple[int, int], list[dict]] = {}
    while True:
        clusters = {}
        for feature in points:
            lon, lat = (feature.get("geometry") or {}).get("coordinates", [None, None])[:2]
            if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
                continue
            x = (_relative_lon(float(lon), bbox.west) - bbox.west) / max(0.001, span_lon)
            y = (float(lat) - bbox.south) / span_lat
            key = (math.floor(x * columns / scale), math.floor(y * rows / scale))
            clusters.setdefault(key, []).append(feature)
        if len(clusters) <= budget or scale >= max(columns, rows):
            break
        scale += 1
    result = []
    for (x, y), members in clusters.items():
        if len(members) == 1:
            result.append(simplify_feature(members[0], zoom))
            continue
        coords = [(member["geometry"]["coordinates"][0], member["geometry"]["coordinates"][1]) for member in members]
        lon = sum(float(item[0]) for item in coords) / len(coords)
        lat = sum(float(item[1]) for item in coords) / len(coords)
        # Nothing of one point (site, phone, link) on the group's card.
        props = {
            key: deepcopy(value)
            for key, value in (members[0].get("properties") or {}).items()
            if key not in CLUSTER_POINT_ONLY_PROPS
        }
        props.update({
            "name": f"{len(members)} points regroupés",
            "clusterCount": len(members),
            "naviguideCatalogId": f"{catalog}:cluster:{int(zoom)}:{scale}:{x}:{y}",
        })
        result.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        })
    return result


class SpatialCatalogIndex:
    """Grille 10° pour éviter de reparcourir un catalogue mondial à chaque pan."""

    def __init__(self, catalog: str, features: Iterable[dict]):
        self.catalog = catalog
        self._entries: list[IndexedFeature] = []
        self._grid: dict[tuple[int, int], set[int]] = {}
        for position, raw in enumerate(features):
            if not isinstance(raw, dict):
                continue
            envelope = feature_envelope(raw)
            if envelope is None:
                continue
            feature = deepcopy(raw)
            properties = feature.get("properties")
            if not isinstance(properties, dict):
                properties = {}
                feature["properties"] = properties
            key = str(properties.get("naviguideCatalogId") or f"{catalog}:{position}")
            properties["naviguideCatalogId"] = key
            entry = IndexedFeature(key, feature, envelope, science_source_of(properties))
            entry_index = len(self._entries)
            self._entries.append(entry)
            for cell in _grid_cells(envelope):
                self._grid.setdefault(cell, set()).add(entry_index)

    def query(self, bbox: Bbox, *, zoom: float, limit: int = MAX_RENDER_FEATURES, source: str | None = None) -> dict:
        candidate_indexes: set[int] = set()
        for cell in _grid_cells(bbox):
            candidate_indexes.update(self._grid.get(cell, set()))
        source_name = (source or "").strip().lower()
        visible = [
            entry
            for index, entry in enumerate(self._entries)
            if index in candidate_indexes
            and _intersects(entry.envelope, bbox)
            and (not source_name or entry.source.lower() == source_name)
        ]
        budget = _lod_budget(float(zoom), limit)
        points = [entry.feature for entry in visible if (entry.feature.get("geometry") or {}).get("type") == "Point"]
        shapes = [entry.feature for entry in visible if (entry.feature.get("geometry") or {}).get("type") != "Point"]
        # Une source de polygones ou de traces ne peut pas évincer indéfiniment les points.
        shape_budget = min(len(shapes), max(1, budget // 3)) if shapes else 0
        simplified_shapes = [simplify_feature(feature, zoom) for feature in shapes[:shape_budget]]
        clustered_points = _cluster_points(points, bbox, max(1, budget - shape_budget), zoom, self.catalog)
        if source_name:
            total = sum(1 for entry in self._entries if entry.source.lower() == source_name)
        else:
            total = len(self._entries)
        return {
            "type": "FeatureCollection",
            "features": [*simplified_shapes, *clustered_points],
            "metadata": {
                "catalog": self.catalog,
                "source": source_name or None,
                "total": total,
                "matched": len(visible),
                "rendered": len(simplified_shapes) + len(clustered_points),
                "budget": budget,
                "clustered": len(points) > len(clustered_points),
            },
        }
