"""Contrat géographique du FeatureCollection Berry (public/route.geojson).

Les boîtes sont recopiées, pas importées. Origine : NO_OFFSET_BOXES de
l'archive routing_ab/cargo.py — détroits et canaux, le bateau doit passer,
sans décalage du trait.
Commentaire d'origine : Panama (-81.0, 8.5, -79.0, 9.7), Suez (32.0, 29.7, 32.7, 31.5).
"""

from __future__ import annotations

# (lon_min, lat_min, lon_max, lat_max)
PANAMA_BOX: tuple[float, float, float, float] = (-81.0, 8.5, -79.0, 9.7)
SUEZ_BOX: tuple[float, float, float, float] = (32.0, 29.7, 32.7, 31.5)


def in_passage_box(
    lon: float,
    lat: float,
    box: tuple[float, float, float, float],
) -> bool:
    """Vrai si le sommet est dans la boîte, bords inclus (même règle que l'archive)."""
    lon_min, lat_min, lon_max, lat_max = box
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max


def line_strings(feature_collection: dict) -> list[dict]:
    """LineString du FeatureCollection : from, to, type, coordinates.

    Les points d'escale (Point) ne sont pas des jambes.
    """
    lines: list[dict] = []
    for feature in feature_collection.get("features") or []:
        geom = (feature or {}).get("geometry") or {}
        if geom.get("type") != "LineString":
            continue
        props = (feature or {}).get("properties") or {}
        lines.append(
            {
                "from": props.get("from") or "",
                "to": props.get("to") or "",
                "type": props.get("type") or "",
                "coordinates": list(geom.get("coordinates") or []),
            }
        )
    return lines


def iter_vertices(feature_collection: dict):
    """Chaque sommet (lon, lat) du fichier, y compris les points d'escale."""
    for feature in feature_collection.get("features") or []:
        geom = (feature or {}).get("geometry") or {}
        yield from _geometry_vertices(geom)


def _geometry_vertices(geom: dict):
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if gtype == "Point":
        yield _pair(coords)
    elif gtype == "LineString":
        for coord in coords or []:
            yield _pair(coord)
    elif gtype == "MultiLineString":
        for line in coords or []:
            for coord in line:
                yield _pair(coord)
    else:
        raise ValueError(f"géométrie inattendue : {gtype!r}")


def _pair(coord) -> tuple[float, float]:
    return float(coord[0]), float(coord[1])
