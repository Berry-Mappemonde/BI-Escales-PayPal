"""Recalcule un FeatureCollection Berry et n'écrit pas le fichier public.

Le module n'est pas chargé au démarrage du serveur. Sans ``--write`` il
imprime un rapport et quitte 0 quand le candidat tient le contrat. Avec
``--write`` il exige ``--dest``. ``public/route.geojson`` et tout lien vers
ce fichier sont refusés avant le calcul.

Chaque feature maritime est recalculée par ``searoute_with_exact_end``.
L'overland Saint-Maur → La Rochelle est recopiée. Aucune feature
Cayenne ↔ Halifax n'est ajoutée. Halifax ↔ Saint-Pierre restent deux
jambes maritimes séparées.

Quand l'écriture a lieu, un JSON est posé à côté du candidat : un objet
par jambe (longueur, hits de terre, hits d'aires sur l'extrait figé,
passage nommé, Halifax, overland, constraintStatus). L'application ne
le charge pas. Panama manquant, un sommet dans Suez, ou une jambe
Halifax en moins : rien n'est écrit.
"""
from __future__ import annotations

import argparse
import copy
import gzip
import json
import os
import sys
import time
from pathlib import Path

_SERVER = Path(__file__).resolve().parent
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

from route_contract import (  # noqa: E402
    PANAMA_BOX,
    SUEZ_BOX,
    in_passage_box,
    iter_vertices,
    line_strings,
)

DEADLINE_S = 90.0
PIN_PATH = Path(__file__).resolve().parent / "tests" / "fixtures" / "amp_nogo_pin.geojson"
LAND_ORACLE_PATH = Path(__file__).resolve().parent / "tests" / "fixtures" / "ne_10m_land_oracle.json.gz"
# Même garde-fou que le moteur et que l'oracle du fichier publié : ≤ 20 km.
_ORACLE_SHORT_M = 20_000.0
_oracle_cache: dict | bool | None = None
_engine_mod = None


def _engine():
    """Moteur déjà importé. Le message « shapefile absent » ne se mêle pas au rapport."""
    global _engine_mod
    if _engine_mod is None:
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            import route_engine as mod
        _engine_mod = mod
    return _engine_mod


def public_route_file() -> Path:
    """Fichier publié. Il peut être passé en ``--src`` ; il ne peut pas être ``--dest``."""
    return Path(__file__).resolve().parent.parent / "public" / "route.geojson"


def dest_targets_public_route(dest: Path | str) -> bool:
    """Vrai si ``dest`` est le fichier public ou un lien (fichier ou dossier) vers lui.

    En cas de doute (chemin illisible), on refuse.
    """
    public = public_route_file()
    try:
        asked = Path(dest).expanduser()
        if not asked.is_absolute():
            asked = Path.cwd() / asked
        asked_abs = Path(os.path.normpath(os.path.abspath(asked)))
        public_abs = Path(os.path.normpath(os.path.abspath(public)))
        if asked_abs == public_abs:
            return True
        if Path(os.path.realpath(asked)) == Path(os.path.realpath(public)):
            return True
        if asked.exists() and public.exists() and os.path.samefile(asked, public):
            return True
    except OSError:
        return True
    return False


def _default_route_fn(start, end, deadline=None):
    from route_engine import searoute_with_exact_end

    if deadline is None:
        deadline = time.monotonic() + DEADLINE_S
    return searoute_with_exact_end(start, end, deadline=deadline)


def _label(props: dict) -> str:
    return f"{props.get('from') or '?'} → {props.get('to') or '?'}"


def _as_lonlat_line(coords) -> list[list[float]] | None:
    if not isinstance(coords, list):
        return None
    out: list[list[float]] = []
    try:
        for coord in coords:
            if coord is None or len(coord) < 2:
                return None
            out.append([float(coord[0]), float(coord[1])])
    except (TypeError, ValueError):
        return None
    if len(out) < 2:
        return None
    return out


def _engine_line(route) -> list[list[float]] | None:
    if not isinstance(route, dict):
        return None
    geom = route.get("geometry") or {}
    if geom.get("type") not in (None, "LineString"):
        return None
    return _as_lonlat_line(geom.get("coordinates"))


def _constraint_open(route) -> bool:
    if not isinstance(route, dict):
        return False
    props = route.get("properties") or {}
    # Reject if constraint is open OR if avoidance status is unavailable
    # (catalogue not loaded, meaning the route couldn't be properly checked).
    constraint = props.get("constraintStatus")
    amp = props.get("ampStatus")
    if constraint == "open":
        return True
    if amp == "unavailable":
        return True
    return False


def _blob(props: dict) -> str:
    return " ".join(str(props.get(key) or "") for key in ("name", "from", "to"))


def _maritime(lines: list[dict], src: str, dst: str) -> list[dict]:
    return [
        line
        for line in lines
        if line["type"] == "maritime" and src in line["from"] and dst in line["to"]
    ]


def contract_violations(feature_collection: dict) -> list[str]:
    """Écarts au contrat d'écriture : Panama, pas sous 40° S, pas Suez, cap, Halifax, une overland.

    Le compte des 35 jambes du fichier publié n'est pas ici : ce garde juge
    le candidat, pas le fichier que l'application charge.
    """
    violations: list[str] = []
    lines = line_strings(feature_collection)
    cayenne = [
        line
        for line in lines
        if "Cayenne" in line["from"] and "Papeete" in line["to"]
    ]
    if not cayenne:
        violations.append("Cayenne → Papeete absente")
    else:
        in_panama = False
        too_far_south = False
        for line in cayenne:
            for lon, lat in (
                (float(coord[0]), float(coord[1])) for coord in line["coordinates"]
            ):
                if lat < -40.0:
                    too_far_south = True
                if in_passage_box(lon, lat, PANAMA_BOX):
                    in_panama = True
        if not in_panama:
            violations.append("aucun sommet de Cayenne → Papeete dans la boîte Panama")
        if too_far_south:
            violations.append("Cayenne → Papeete descend sous 40° S")
    suez = [
        (lon, lat)
        for lon, lat in iter_vertices(feature_collection)
        if in_passage_box(lon, lat, SUEZ_BOX)
    ]
    if suez:
        violations.append("sommet dans la boîte Suez")
    named = any(
        "Bonne Espérance" in _blob((feature.get("properties") or {}))
        for feature in feature_collection.get("features") or []
    )
    if not named:
        violations.append("cap de Bonne Espérance non nommé")
    if len(_maritime(lines, "Halifax", "Saint-Pierre")) != 1 or len(
        _maritime(lines, "Saint-Pierre", "Halifax")
    ) != 1:
        violations.append("Halifax ↔ Saint-Pierre doit rester deux jambes maritimes")
    joined = []
    for feature in feature_collection.get("features") or []:
        props = feature.get("properties") or {}
        src = props.get("from") or ""
        dst = props.get("to") or ""
        if ("Cayenne" in src and "Halifax" in dst) or (
            "Halifax" in src and "Cayenne" in dst
        ):
            joined.append((src, dst))
    if joined:
        violations.append("feature Cayenne ↔ Halifax")
    overland = [
        feature
        for feature in feature_collection.get("features") or []
        if (feature.get("properties") or {}).get("type") == "overland"
    ]
    if len(overland) != 1:
        violations.append("une seule jambe overland attendue")
    else:
        props = overland[0].get("properties") or {}
        geom = overland[0].get("geometry") or {}
        coords = geom.get("coordinates") or []
        if not str(props.get("from") or "").startswith("Saint-Maur") or props.get("to") != "La Rochelle":
            violations.append("l'overland n'est pas Saint-Maur → La Rochelle")
        if geom.get("type") != "LineString" or len(coords) != 2:
            violations.append("l'overland Saint-Maur n'est plus la droite d'origine")
    return violations


def _overland(feature_collection: dict) -> list[dict]:
    return [
        feature
        for feature in feature_collection.get("features") or []
        if (feature.get("properties") or {}).get("type") == "overland"
    ]


def rebuild_collection(feature_collection: dict, route_fn, deadline: float | None = None) -> tuple[dict, list[str], list[dict]]:
    """Retourne ``(candidat, violations, manifeste)``. N'écrit rien.

    Le manifeste est une liste vide dès qu'une violation interdit l'écriture.
    ``route_fn(start, end, deadline=...)`` renvoie une feature GeoJSON, ou
    rien si la jambe n'a pas de ligne. Une jambe sans ligne est absente du
    candidat. ``constraintStatus == open`` interdit l'écriture.
    """
    if deadline is None:
        deadline = time.monotonic() + DEADLINE_S
    candidate = copy.deepcopy(feature_collection)
    features: list[dict] = []
    statuses: list = []
    failures: list[str] = []
    open_legs: list[str] = []
    for feature in feature_collection.get("features") or []:
        geom = (feature or {}).get("geometry") or {}
        props = (feature or {}).get("properties") or {}
        if props.get("type") != "maritime":
            features.append(copy.deepcopy(feature))
            statuses.append(_status_text(props.get("constraintStatus")))
            continue
        label = _label(props)
        if geom.get("type") != "LineString":
            failures.append(f"{label} : géométrie maritime inattendue")
            continue
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            failures.append(f"{label} : extrémités manquantes")
            continue
        start = (float(coords[0][0]), float(coords[0][1]))
        end = (float(coords[-1][0]), float(coords[-1][1]))
        try:
            route = route_fn(start, end, deadline=deadline)
        except Exception as exc:
            failures.append(f"{label} : {exc}")
            continue
        line = _engine_line(route)
        if line is None:
            failures.append(f"{label} : jambe maritime non recalculée")
            continue
        if _constraint_open(route):
            open_legs.append(label)
        cloned = copy.deepcopy(feature)
        cloned["geometry"]["coordinates"] = line
        features.append(cloned)
        route_props = (route.get("properties") or {}) if isinstance(route, dict) else {}
        statuses.append(_status_text(route_props.get("constraintStatus")))
    candidate["features"] = features
    violations = contract_violations(candidate)
    if _overland(feature_collection) != _overland(candidate):
        violations.append("overland Saint-Maur modifiée")
    violations.extend(failures)
    for label in open_legs:
        violations.append(f"constraintStatus open : {label}")
    manifest: list[dict] = []
    if not violations:
        try:
            manifest = build_manifest(features, statuses)
        except OSError as exc:
            violations.append(f"extrait d'aires illisible : {exc}")
    return candidate, violations, manifest


def format_report(candidate: dict, violations: list[str], *, write: bool, manifest: str | None = None) -> str:
    lines = line_strings(candidate)
    panama = any(
        in_passage_box(float(coord[0]), float(coord[1]), PANAMA_BOX)
        for line in lines
        if "Cayenne" in line["from"] and "Papeete" in line["to"]
        for coord in line["coordinates"]
    )
    suez = [
        pair
        for pair in iter_vertices(candidate)
        if in_passage_box(pair[0], pair[1], SUEZ_BOX)
    ]
    cape = any(
        "Bonne Espérance" in _blob((feature.get("properties") or {}))
        for feature in candidate.get("features") or []
    )
    halifax = len(_maritime(lines, "Halifax", "Saint-Pierre")) + len(
        _maritime(lines, "Saint-Pierre", "Halifax")
    )
    overland = [
        feature
        for feature in candidate.get("features") or []
        if (feature.get("properties") or {}).get("type") == "overland"
    ]
    cayenne_halifax = [
        feature
        for feature in candidate.get("features") or []
        if _joins_cayenne_halifax(feature.get("properties") or {})
    ]
    open_count = sum(1 for item in violations if item.startswith("constraintStatus open"))
    rows = [
        f"Cayenne → Papeete : {'Panama présent' if panama else 'Panama absent'}",
        f"Suez : {'aucun sommet' if not suez else f'{len(suez)} sommet(s)'}",
        f"Bonne Espérance : {'nommé' if cape else 'absent'}",
        f"Halifax ↔ Saint-Pierre : {halifax} jambes maritimes",
        f"overland : {len(overland)}",
        f"Cayenne ↔ Halifax : {'aucune' if not cayenne_halifax else str(len(cayenne_halifax))}",
        f"contraintes ouvertes : {'aucune' if open_count == 0 else str(open_count)}",
        f"écriture : {'oui' if write and not violations else 'non'}",
        f"manifeste : {manifest if write and manifest and not violations else 'non'}",
        f"verdict : {'conforme' if not violations else 'refusé'}",
    ]
    rows.extend(f"- {item}" for item in violations)
    return "\n".join(rows) + "\n"


def _joins_cayenne_halifax(props: dict) -> bool:
    src = props.get("from") or ""
    dst = props.get("to") or ""
    return ("Cayenne" in src and "Halifax" in dst) or ("Halifax" in src and "Cayenne" in dst)


def manifest_path_for(dest: Path) -> Path:
    """``candidat.geojson`` et ``candidat.manifest.json`` dans le même dossier."""
    asked = Path(dest)
    return asked.with_name(f"{asked.stem}.manifest.json")


def _status_text(value) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _halifax_leg(props: dict) -> bool:
    if props.get("type") != "maritime":
        return False
    src = props.get("from") or ""
    dst = props.get("to") or ""
    return ("Halifax" in src and "Saint-Pierre" in dst) or (
        "Saint-Pierre" in src and "Halifax" in dst
    )


def _saint_maur_overland(props: dict) -> bool:
    return (
        props.get("type") == "overland"
        and str(props.get("from") or "").startswith("Saint-Maur")
        and props.get("to") == "La Rochelle"
    )


def _passage_name(props: dict, coords: list) -> str | None:
    """Panama ou Suez dès qu'un sommet est dans la boîte ; sinon le cap nommé."""
    found: list[str] = []
    for coord in coords:
        if coord is None or len(coord) < 2:
            continue
        try:
            lon, lat = float(coord[0]), float(coord[1])
        except (TypeError, ValueError):
            continue
        if in_passage_box(lon, lat, PANAMA_BOX) and "Panama" not in found:
            found.append("Panama")
        if in_passage_box(lon, lat, SUEZ_BOX) and "Suez" not in found:
            found.append("Suez")
    if "Bonne Espérance" in _blob(props) and "Bonne Espérance" not in found:
        found.append("Bonne Espérance")
    if not found:
        return None
    return "+".join(found)


def _longueur_km(coords: list) -> float | None:
    if len(coords) < 2:
        return None
    try:
        clean = [[float(coord[0]), float(coord[1])] for coord in coords]
        value = float(_engine().route_length_km(clean))
    except (TypeError, ValueError, IndexError):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return round(value, 3)


def _sampler_hits(coords: list) -> int:
    segment_crosses_land = _engine().segment_crosses_land
    hits = 0
    for start, end in zip(coords, coords[1:]):
        if start is None or end is None or len(start) < 2 or len(end) < 2:
            continue
        try:
            crossed = segment_crosses_land(
                float(start[0]), float(start[1]), float(end[0]), float(end[1])
            )
        except Exception:
            crossed = False
        if crossed:
            hits += 1
    return hits


def _pin_items() -> list[dict]:
    """Items interdits de l'extrait figé. Aucun GET /amp/nogo."""
    from amp_nogo import _item_from_feature

    path = Path(PIN_PATH)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise OSError(f"extrait d'aires illisible : {exc}") from exc
    if not isinstance(raw, dict):
        raise OSError("extrait d'aires illisible : FeatureCollection attendu")
    items = []
    for feat in raw.get("features") or []:
        item = _item_from_feature(feat)
        if item:
            items.append(item)
    if not items:
        raise OSError("extrait d'aires illisible : aucun item interdit")
    return items


def _short_arc(lon1: float, lon2: float) -> tuple[float, float]:
    """Court arc : ``lon2`` déplié à moins de 180° de ``lon1``."""
    from longitude import unwrap_lon

    return float(lon1), unwrap_lon(float(lon1), float(lon2))


def _wrap_lon(lon: float) -> float:
    from longitude import wrap_lon

    return wrap_lon(lon)


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


def _segment_hits_area(lon1, lat1, lon2, lat2, item) -> bool:
    """Vrai si un échantillon du court arc tombe dans l'item, via point_in_geom."""
    from amp_traffic import point_in_geom

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
        t = t0 + (t1 - t0) * (k / n if n else 0.0)
        if point_in_geom(_wrap_lon(lon1 + dlon * t), lat1 + dlat * t, geom):
            return True
    return False


def _area_hits(coords: list, items: list[dict]) -> int:
    hits = 0
    for start, end in zip(coords, coords[1:]):
        if start is None or end is None or len(start) < 2 or len(end) < 2:
            continue
        if any(
            _segment_hits_area(start[0], start[1], end[0], end[1], item)
            for item in items
        ):
            hits += 1
    return hits


def _oracle_ready():
    """Polygones Natural Earth déjà chargés, sinon l'extrait du dépôt. None sans shapely."""
    global _oracle_cache
    if _oracle_cache is not None:
        return None if _oracle_cache is False else _oracle_cache
    try:
        from shapely.geometry import LineString, box as shapely_box, shape
        from shapely.ops import unary_union
        from shapely.strtree import STRtree
    except ImportError:
        _oracle_cache = False
        return None
    polygons: list = []
    try:
        tree = _engine()._NE_TREE
        if tree is not None:
            polygons = [
                geom
                for geom in tree.geometries
                if geom is not None and not geom.is_empty
            ]
    except Exception:
        polygons = []
    if not polygons and Path(LAND_ORACLE_PATH).is_file():
        try:
            raw = json.loads(gzip.decompress(Path(LAND_ORACLE_PATH).read_bytes()))
        except (OSError, json.JSONDecodeError, UnicodeError, ValueError, gzip.BadGzipFile):
            raw = {}
        for feature in (raw.get("features") if isinstance(raw, dict) else None) or []:
            geom = (feature or {}).get("geometry") or {}
            if geom.get("type") != "Polygon":
                continue
            poly = shape(geom)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly is not None and not poly.is_empty:
                polygons.append(poly)
    if not polygons:
        _oracle_cache = False
        return None
    _oracle_cache = {
        "polygons": polygons,
        "tree": STRtree(polygons),
        "boxes": (
            shapely_box(PANAMA_BOX[0], PANAMA_BOX[1], PANAMA_BOX[2], PANAMA_BOX[3]),
            shapely_box(SUEZ_BOX[0], SUEZ_BOX[1], SUEZ_BOX[2], SUEZ_BOX[3]),
        ),
        "LineString": LineString,
        "union": unary_union,
    }
    return _oracle_cache


def _oracle_lines(lon1: float, lat1: float, lon2: float, lat2: float, ready: dict) -> list:
    split_antimeridian = _engine().split_antimeridian
    lines = []
    line_type = ready["LineString"]
    for lon_a, lat_a, lon_b, lat_b in split_antimeridian(lon1, lat1, lon2, lat2):
        line = line_type([(lon_a, lat_a), (lon_b, lat_b)])
        if line.length:
            lines.append(line)
    return lines


def _overlap_m(geom) -> float:
    from geographiclib.geodesic import Geodesic

    if geom is None or geom.is_empty:
        return 0.0
    kind = geom.geom_type
    if kind == "LineString":
        coords = list(geom.coords)
    elif kind in ("MultiLineString", "GeometryCollection"):
        return sum(_overlap_m(part) for part in geom.geoms)
    else:
        return 0.0
    total = 0.0
    geod = Geodesic.WGS84
    for start, end in zip(coords, coords[1:]):
        total += geod.Inverse(start[1], start[0], end[1], end[0])["s12"]
    return total


def _overlap_samples(geom):
    if geom is None or geom.is_empty:
        return
    kind = geom.geom_type
    if kind == "Point":
        yield geom.x, geom.y
        return
    if kind == "LineString":
        count = max(1, int(geom.length / 0.02))
        for step in range(count + 1):
            point = geom.interpolate(step / count, normalized=True)
            yield point.x, point.y
        return
    if kind in ("MultiLineString", "MultiPoint", "GeometryCollection"):
        for part in geom.geoms:
            yield from _overlap_samples(part)


def _away_from_ends(geom, lon1: float, lat1: float, lon2: float, lat2: float) -> bool:
    from geographiclib.geodesic import Geodesic

    geod = Geodesic.WGS84
    for lon, lat in _overlap_samples(geom):
        to_start = geod.Inverse(lat, lon, lat1, lon1)["s12"]
        to_end = geod.Inverse(lat, lon, lat2, lon2)["s12"]
        if to_start > _ORACLE_SHORT_M and to_end > _ORACLE_SHORT_M:
            return True
    return False


def _oracle_crosses(lon1: float, lat1: float, lon2: float, lat2: float, ready: dict) -> bool:
    pieces = []
    polygons = ready["polygons"]
    tree = ready["tree"]
    for line in _oracle_lines(lon1, lat1, lon2, lat2, ready):
        for index in tree.query(line, predicate="intersects"):
            hit = line.intersection(polygons[int(index)])
            if not hit.is_empty:
                pieces.append(hit)
    if not pieces:
        return False
    overlap = ready["union"](pieces)
    for passage in ready["boxes"]:
        overlap = overlap.difference(passage)
    if overlap.is_empty:
        return False
    if _overlap_m(overlap) > _ORACLE_SHORT_M:
        return True
    return _away_from_ends(overlap, lon1, lat1, lon2, lat2)


def _oracle_hits(coords: list) -> int | None:
    ready = _oracle_ready()
    if ready is None:
        return None
    hits = 0
    for start, end in zip(coords, coords[1:]):
        if start is None or end is None or len(start) < 2 or len(end) < 2:
            continue
        if _oracle_crosses(float(start[0]), float(start[1]), float(end[0]), float(end[1]), ready):
            hits += 1
    return hits


def land_hit_counts(coords: list) -> dict:
    """Hits de terre : échantillonneur du moteur, et l'oracle shapely s'il est là."""
    return {"echantillonneur": _sampler_hits(coords), "oracle": _oracle_hits(coords)}


def build_manifest(features: list[dict], statuses: list) -> list[dict]:
    """Un objet par LineString. Les points d'escale ne sont pas des jambes."""
    items = _pin_items()
    rows = []
    for feature, status in zip(features, statuses):
        geom = (feature or {}).get("geometry") or {}
        if geom.get("type") != "LineString":
            continue
        props = (feature or {}).get("properties") or {}
        coords = list(geom.get("coordinates") or [])
        rows.append(
            {
                "from": props.get("from") or "",
                "to": props.get("to") or "",
                "longueur": _longueur_km(coords),
                "hitsTerre": land_hit_counts(coords),
                "hitsAires": _area_hits(coords, items),
                "passageNomme": _passage_name(props, coords),
                "jambeHalifax": _halifax_leg(props),
                "overlandSaintMaur": _saint_maur_overland(props),
                "constraintStatus": _status_text(status),
            }
        )
    return rows


def _write_text_atomic(dest: Path, payload: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_name(dest.name + ".tmp")
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, dest)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def _write_candidate(dest: Path, candidate: dict) -> None:
    if dest_targets_public_route(dest):
        raise OSError("public/route.geojson")
    payload = json.dumps(candidate, ensure_ascii=False, indent=2) + "\n"
    _write_text_atomic(dest, payload)


def _write_pair(dest: Path, candidate: dict, manifest: list) -> Path:
    """Écrit le candidat puis le manifeste. Si le second échoue, retire le premier."""
    manifest_path = manifest_path_for(dest)
    if dest_targets_public_route(dest) or dest_targets_public_route(manifest_path):
        raise OSError("public/route.geojson")
    _write_candidate(dest, candidate)
    try:
        payload = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        _write_text_atomic(manifest_path, payload)
    except OSError:
        dest.unlink(missing_ok=True)
        raise
    return manifest_path


def main(argv: list[str] | None = None, route_fn=None) -> int:
    parser = argparse.ArgumentParser(description="Recalcule un FeatureCollection Berry sans publier le fichier public.")
    parser.add_argument("--src", required=True, help="FeatureCollection GeoJSON (pas un chemin figé)")
    parser.add_argument("--write", action="store_true", help="Écrit le candidat. Exige --dest.")
    parser.add_argument("--dest", default=None, help="Fichier candidat. Interdit : public/route.geojson.")
    parser.add_argument("--write-film", action="store_true", help="Pré-écrit les variantes film (FR/EN) après rebuild.")
    args = parser.parse_args(argv)
    if args.write and not args.dest:
        print("refusé : --write exige --dest", file=sys.stderr)
        return 2
    if args.write and dest_targets_public_route(args.dest):
        print(
            "refusé : --dest ne peut pas être public/route.geojson ni un lien vers ce fichier",
            file=sys.stderr,
        )
        return 2
    try:
        feature_collection = json.loads(Path(args.src).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        print(f"source illisible : {exc}", file=sys.stderr)
        return 2
    if not isinstance(feature_collection, dict):
        print("source illisible : FeatureCollection attendu", file=sys.stderr)
        return 2
    fn = route_fn or _default_route_fn
    try:
        candidate, violations, manifest = rebuild_collection(feature_collection, fn)
    except (TypeError, ValueError, KeyError) as exc:
        print(f"candidat illisible : {exc}", file=sys.stderr)
        return 1
    wrote = False
    manifest_name = None
    if args.write and not violations:
        dest = Path(args.dest)
        if not dest.is_absolute():
            dest = Path.cwd() / dest
        if dest_targets_public_route(dest):
            print(
                "refusé : --dest ne peut pas être public/route.geojson ni un lien vers ce fichier",
                file=sys.stderr,
            )
            return 2
        try:
            written = _write_pair(dest, candidate, manifest)
            wrote = True
            manifest_name = written.name
        except OSError as exc:
            violations.append(f"écriture impossible : {exc}")
    # Fix 3 : Auto-pré-écriture des variantes film
    if args.write_film and not violations and wrote:
        try:
            from official_store import write_film_on_click, serve_film, put, get, READY, _log_fill_written
            from datetime import datetime
            lg = "fr"
            secs = 150
            cached = serve_film(lang=lg, seconds=secs, style="written")
            if not (cached.get("hasWritten") and cached.get("status") == READY):
                when = datetime.utcnow()
                write_film_on_click(lang=lg, seconds=secs, cascade=None, now=when)
                _log_fill_written(f"rebuild : film pré-écrit {lg} {secs}s")
        except Exception as e:
            _log_fill_written(f"rebuild : erreur film pré-écriture {e}")
    sys.stdout.write(format_report(candidate, violations, write=wrote, manifest=manifest_name))
    if violations:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
