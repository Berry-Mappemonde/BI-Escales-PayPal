"""Moteur searoute + évitement des terres — extrait de naviguide-api/main.py."""
from __future__ import annotations

import contextvars
import hashlib
import math
import pathlib
import time
from typing import Optional

from geographiclib.geodesic import Geodesic

from longitude import delta_lon, unwrap_lon, wrap_lon  # noqa: F401  (wrap_lon : API de main.py)
from route_contract import PANAMA_BOX, SUEZ_BOX, in_passage_box

from mem_limits import ROUTE_CACHE_MAX, lru_set
from shipping_lanes import attach_anti_shipping

try:
    from global_land_mask import globe as _globe
    _LAND_MASK_AVAILABLE = True
except ImportError:
    _globe = None
    _LAND_MASK_AVAILABLE = False

import shapely.geometry
import shapely.strtree

_NE_TREE: Optional[shapely.strtree.STRtree] = None

def _load_ne_land_tree() -> Optional[shapely.strtree.STRtree]:
    """
    Load Natural Earth 1:10m land + minor-islands shapefiles and build an
    STRtree for fast point-in-polygon queries.  Returns None on failure.
    """
    try:
        import shapefile as pyshp
        geo_dir = pathlib.Path(__file__).parent / "geo_data"
        polys: list = []
        for fname in ("ne_10m_land.shp", "ne_10m_minor_islands.shp"):
            shp = geo_dir / fname
            if not shp.exists():
                continue
            sf = pyshp.Reader(str(shp))
            for shape in sf.shapes():
                geo = shapely.geometry.shape(shape.__geo_interface__)
                if geo.geom_type == "Polygon":
                    if geo.is_valid and not geo.is_empty:
                        polys.append(geo)
                elif geo.geom_type == "MultiPolygon":
                    for sub in geo.geoms:
                        if sub.is_valid and not sub.is_empty:
                            polys.append(sub)
        if polys:
            print(f"✅ NE land mask loaded: {len(polys)} polygons")
            return shapely.strtree.STRtree(polys)
    except Exception as exc:
        print(f"⚠️  NE land mask unavailable: {exc}")
    return None

_NE_TREE = _load_ne_land_tree()


def _is_land_hires(lat: float, lon: float) -> bool:
    """
    Combined high-resolution land check:
    1. global_land_mask (1/4° grid, very fast) — catches continents/large islands
    2. Natural Earth 1:10m STRtree — catches smaller islands (Nias, Mentawai…)
    Returns True if EITHER source classifies the point as land.
    """
    # Primary: fast 1/4° grid check
    if _LAND_MASK_AVAILABLE:
        try:
            if bool(_globe.is_land(lat, lon)):
                return True
        except Exception:
            pass
    # Secondary: high-resolution shapely tree for small islands
    if _NE_TREE is not None:
        pt = shapely.geometry.Point(lon, lat)
        return len(_NE_TREE.query(pt, predicate="intersects")) > 0
    return False


# ── Land-waypoint sanitiser ───────────────────────────────────────────────────

def _has_nearby_ocean(lat: float, lon: float, radius_deg: float = 1.5) -> bool:
    """
    Return True if there is at least one ocean cell within *radius_deg* of
    (lat, lon). Used to distinguish genuine inland waypoints from narrow
    maritime passages like the Suez Canal, where global_land_mask at 1/4°
    incorrectly labels every canal cell as land even though the point is a
    valid maritime route node.
    """
    if not _LAND_MASK_AVAILABLE:
        return True   # no mask available → assume navigable
    steps = [-radius_deg, -radius_deg * 0.5, 0.0, radius_deg * 0.5, radius_deg]
    for dlat in steps:
        for dlon in steps:
            try:
                if not _globe.is_land(lat + dlat, lon + dlon):
                    return True
            except Exception:
                pass
    return False


def _latitude_where_lon_crosses(lat1: float, lon1: float, lat2: float, lon2: float,
                                boundary: float) -> float:
    """Latitude de la géodésique là où la longitude dépliée atteint ±180°."""
    try:
        line = Geodesic.WGS84.InverseLine(lat1, lon1, lat2, lon2)
        total = float(line.s13)
    except Exception:
        return lat1
    if total <= 0.0 or not math.isfinite(total):
        return lat1
    going_east = boundary > 0.0

    def _ulon(distance: float) -> float:
        return unwrap_lon(lon1, line.Position(distance)["lon2"])

    lo, hi = 0.0, total
    for _ in range(48):
        mid = (lo + hi) * 0.5
        crossed = _ulon(mid) >= boundary if going_east else _ulon(mid) <= boundary
        if crossed:
            hi = mid
        else:
            lo = mid
    try:
        lat = float(line.Position(hi)["lat2"])
    except Exception:
        return lat1
    return lat if math.isfinite(lat) else lat1


def split_antimeridian(lon1: float, lat1: float, lon2: float, lat2: float):
    """Un ou deux segments repliés dans [-180, 180], coupés sur ±180°.

    Le plus court arc qui sort de [-180, 180] est coupé au méridien : le
    morceau oriental finit à 180, le morceau occidental commence à -180
    (le même point). Un segment qui ne traverse pas est rendu tel quel,
    longitudes repliées (identité si elles étaient déjà dans l'intervalle).
    """
    try:
        lat1_f, lat2_f = float(lat1), float(lat2)
        a, b = wrap_lon(float(lon1)), wrap_lon(float(lon2))
    except (TypeError, ValueError):
        return ((lon1, lat1, lon2, lat2),)
    if not all(math.isfinite(v) for v in (a, b, lat1_f, lat2_f)):
        return ((lon1, lat1, lon2, lat2),)
    end_u = a + delta_lon(a, b)
    if -180.0 <= end_u <= 180.0:
        return ((a, lat1_f, b, lat2_f),)
    boundary = 180.0 if end_u > 180.0 else -180.0
    other = -boundary
    lat_cross = _latitude_where_lon_crosses(lat1_f, a, lat2_f, b, boundary)
    if not math.isfinite(lat_cross):
        frac = (boundary - a) / (end_u - a)
        lat_cross = lat1_f + (lat2_f - lat1_f) * frac
    raw = (
        (a, lat1_f, boundary, lat_cross),
        (other, lat_cross, b, lat2_f),
    )
    pieces = []
    for lon_a, la, lon_b, lb in raw:
        if abs(delta_lon(lon_a, lon_b)) < 1e-9 and abs(la - lb) < 1e-9:
            continue
        pieces.append((lon_a, la, lon_b, lb))
    if not pieces:
        return ((a, lat1_f, b, lat2_f),)
    return tuple(pieces)


# Panama et Suez : un segment dont les deux sommets sont dans la même boîte,
# jusqu'à cette longueur, est le passage searoute, pas une traversée à
# détourner. Au-delà, le lien peut être coupé en deux s'il reste dans la boîte.
NAMED_PASSAGE_MAX_M = 60_000.0
_NAMED_PASSAGE_BOXES = (PANAMA_BOX, SUEZ_BOX)


def _shared_passage_box(lon1: float, lat1: float, lon2: float, lat2: float):
    """La boîte Panama ou Suez qui contient les deux bouts, sinon None."""
    for box in _NAMED_PASSAGE_BOXES:
        if in_passage_box(lon1, lat1, box) and in_passage_box(lon2, lat2, box):
            return box
    return None


def segment_in_named_passage(coords) -> bool:
    """Vrai seulement si les deux bouts sont dans la même boîte et la longueur ≤ 60 km.

    Panama ou Suez, pas les deux. Un seul bout dans la boîte, ou une
    géodésique plus longue que le plafond, n'est pas un passage nommé.
    """
    if not coords or len(coords) < 2:
        return False
    try:
        lon1, lat1 = float(coords[0][0]), float(coords[0][1])
        lon2, lat2 = float(coords[-1][0]), float(coords[-1][1])
    except (TypeError, ValueError, IndexError):
        return False
    if not all(math.isfinite(v) for v in (lon1, lat1, lon2, lat2)):
        return False
    if _shared_passage_box(lon1, lat1, lon2, lat2) is None:
        return False
    try:
        dist = Geodesic.WGS84.Inverse(lat1, lon1, lat2, lon2)["s12"]
    except Exception:
        return False
    return math.isfinite(dist) and dist <= NAMED_PASSAGE_MAX_M


def _segment_crosses_land(lon1: float, lat1: float, lon2: float, lat2: float,
                          n_samples: int = 30, _folded: bool = False) -> bool:
    """
    Return True if the great-circle segment from (lon1,lat1)→(lon2,lat2)
    crosses any land, including small islands and archipelagos.

    Uses the combined high-resolution check (_is_land_hires) which queries
    both global_land_mask (1/4° grid) and the Natural Earth 1:10m STRtree,
    so islands like Nias and the Mentawai group are reliably detected.
    Dense sampling (30 pts) catches features as narrow as ~20 km.

    A short arc that crosses ±180° is cut first (split_antimeridian). Each
    folded piece is sampled on its own side of the meridian. The longitude
    jump alone is not a reason to skip the check.
    """
    if not _LAND_MASK_AVAILABLE and _NE_TREE is None:
        return False
    if not _folded:
        pieces = split_antimeridian(lon1, lat1, lon2, lat2)
        if len(pieces) > 1:
            return any(
                _segment_crosses_land(p_lon1, p_lat1, p_lon2, p_lat2, n_samples, True)
                for p_lon1, p_lat1, p_lon2, p_lat2 in pieces
            )
        lon1, lat1, lon2, lat2 = pieces[0]
    geod = Geodesic.WGS84
    try:
        line = geod.InverseLine(lat1, lon1, lat2, lon2)
        total_dist = line.s13
    except Exception:
        return False

    if total_dist < 1000:             # < 1 km — skip micro-segments (canal links)
        return False

    # Passage nommé, avant le garde-fou des 20 km : les deux sommets dans
    # la même boîte Panama ou Suez, jusqu'à 60 km. Le masque peut dire
    # « terre » sur les cellules du canal ; ce n'est pas une traversée.
    if segment_in_named_passage([[lon1, lat1], [lon2, lat2]]):
        return False

    # Hors boîte : port ou détroit court. Un segment ≤ 20 km dont un bout
    # est à terre reste un passage, pas une traversée. Au-delà de 20 km,
    # la terre intermédiaire compte, même si un bout est sur une île.
    if total_dist <= 20_000 and (_is_land_hires(lat1, lon1) or _is_land_hires(lat2, lon2)):
        return False

    try:
        # When an endpoint is on an island/harbour, skip samples near that endpoint
        # to avoid false positives caused by the urban/coastal land mass surrounding
        # a port (e.g. Pointe-à-Pitre, Fort-de-France).  We skip the last 25 % of
        # samples so that real crossings further back along the segment are still
        # caught, while short "harbour approach" land hits are ignored.
        start_k = 3 if _is_land_hires(lat1, lon1) else 1
        end_k   = (n_samples * 3 // 4) if _is_land_hires(lat2, lon2) else n_samples

        # Require at least 2 *consecutive* land samples before reporting a crossing.
        # A single land sample on a ~75 km segment corresponds to a ~1–2 km island
        # or reef (e.g. Torres Strait cays, Maldive atolls) whose geodesic clip is a
        # false positive — searoute already routes around such obstacles correctly.
        # Real land masses (Basse-Terre ~30 km, Nias ~130 km, continents) produce
        # many consecutive samples and are still reliably detected.
        consecutive = 0
        for k in range(start_k, end_k):
            pos = line.Position(k / n_samples * total_dist)
            if _is_land_hires(pos["lat2"], pos["lon2"]):
                consecutive += 1
                if consecutive >= 2:
                    return True       # confirmed crossing: ≥ 2 consecutive land samples
            else:
                consecutive = 0      # reset on any ocean sample
    except Exception:
        pass
    return False


def _normalize_antimeridian(coords: list, prev_lon: float) -> list:
    """
    Walk through a list of [lon, lat] waypoints and adjust each longitude so
    that the sequence is continuous — no ±180° jumps.  This mirrors the same
    correction applied inside `_densify_coords` and is required whenever new
    waypoints are inserted by `searoute` or by a perpendicular detour, because
    those paths do not go through the densifier.

    `prev_lon` is the longitude of the last already-accepted waypoint (the
    point that precedes the first element of `coords`).
    Returns a NEW list with corrected longitudes (input is not mutated).
    """
    result = []
    for pt in coords:
        lon = unwrap_lon(prev_lon, pt[0])
        result.append([lon, pt[1]])
        prev_lon = lon
    return result


def unwrap_path(coords: list, ref_lon: float) -> list:
    """Déplie une polyligne relativement à *ref_lon* (aucun saut de 360°)."""
    if not coords:
        return []
    return _normalize_antimeridian(list(coords), float(ref_lon))


class RouteBusy(Exception):
    """No answer in time (deadline passed, or every searoute slot busy).
    Not « no route »: the caller says « busy, try again » (503)."""


# Set by `_invoke_searoute` when it gave up for lack of time or slot.
_SEAROUTE_BUSY: contextvars.ContextVar[bool] = contextvars.ContextVar("searoute_busy", default=False)


def _time_left(deadline: float | None) -> float | None:
    return None if deadline is None else deadline - time.monotonic()


def _sub_searoute(a: list, b: list, deadline: float | None = None):
    """searoute(a, b) for a detour, in the worker process (never in this one).
    With a deadline, uses what is left of it and raises RouteBusy once spent;
    without one, a time-out is just « no detour »."""
    from searoute_worker import RUNNER, TIMED_OUT, WorkerDied  # noqa: PLC0415

    left = _time_left(deadline)
    timeout_s = SEAROUTE_TIMEOUT_S if left is None else min(SEAROUTE_TIMEOUT_S, left)
    if timeout_s <= 0:
        raise RouteBusy("route deadline reached")
    try:
        sub = RUNNER.run(SEAROUTE_TARGET, ([a[0], a[1]], [b[0], b[1]]), timeout_s)
    except WorkerDied as exc:
        if deadline is not None:
            raise RouteBusy(str(exc)) from exc
        return None
    if sub is TIMED_OUT:
        if deadline is not None:
            raise RouteBusy("route deadline reached")
        return None
    return sub


def _reroute_segment(a: list, b: list, deadline: float | None = None) -> list:
    """
    Try to replace a land-crossing direct segment [a→b] with a proper
    maritime sub-route from searoute.
    Returns a list of [lon, lat] points that follow 'a' (i.e. does NOT
    include 'a' itself, DOES include 'b').
    Falls back to [b] (direct hop) when searoute also fails.
    """
    try:
        sub = _sub_searoute(a, b, deadline)
        if sub and sub.get("geometry", {}).get("coordinates"):
            sub_coords = sub["geometry"]["coordinates"]
            # Only use searoute result if it contains at least one intermediate
            # waypoint (> 2 points).  When searoute returns just [A, B] it means
            # it has no better route — fall through to perpendicular-offset strategy.
            if len(sub_coords) > 2:
                # Normalize antimeridian continuity relative to point 'a'
                normalized = _normalize_antimeridian(sub_coords[1:], a[0])
                return normalized    # exclude 'a' — already in result
    except RouteBusy:
        raise
    except Exception:
        pass
    return [b]   # fallback: direct connection (still not ideal, but keeps route valid)


def _fix_land_crossing_segments(coords: list, deadline: float | None = None) -> list:
    """
    Walk through consecutive waypoint pairs.  For any segment that crosses
    deeply-inland land, replace it with a maritime sub-route obtained from
    searoute.  Non-crossing segments are kept as-is for performance.
    """
    if not _LAND_MASK_AVAILABLE or len(coords) < 2:
        return coords

    result = [coords[0]]

    for i in range(len(coords) - 1):
        a = result[-1]        # last accepted/inserted point
        b = coords[i + 1]

        if _segment_crosses_land(a[0], a[1], b[0], b[1]):
            replacement = _reroute_segment(a, b, deadline)
            result.extend(replacement)
        else:
            result.append(b)

    return result


def _find_land_crossing_detour(a: list, b: list, deadline: float | None = None) -> list:
    """
    Given a segment A→B known to cross land, return a replacement list of
    waypoints (excluding A, including B) that navigates around the land.

    Tries in order:
      1. searoute(A, B)  — precomputed maritime routing graph
      2. Perpendicular-offset midpoint at 50 / 100 / 150 / 200 km on each
         side, evaluated at fractions 0.5 / 0.33 / 0.67 along the segment.
         The first candidate whose two sub-segments are both land-free is used.

    Falls back to [B] (direct hop) if every strategy fails.
    """
    # Strategy 1: maritime routing library
    geod = Geodesic.WGS84
    try:
        sub = _sub_searoute(a, b, deadline)
        if sub and sub.get("geometry", {}).get("coordinates"):
            sub_coords = sub["geometry"]["coordinates"]
            # Only accept if searoute added at least one INTERMEDIATE waypoint
            # (> 2 points = start + intermediate(s) + end).  When it returns
            # just [A, B] it found no better route — fall through to Strategy 2.
            if len(sub_coords) > 2:
                # Sanity check: reject spurious circumnavigations.
                # searoute's graph can produce absurd round-trip detours (e.g.
                # Torres Strait region: a 70 km or even 400 km direct segment
                # routed via a 2 000 km Coral Sea loop).  The per-point check
                # (distance from each intermediate to both endpoints) can miss
                # cases where the segment is long enough that a circumnavigation
                # intermediate lies within 3× of one endpoint.
                #
                # Primary check — total route length vs direct distance:
                # if the sum of all sub-segment distances exceeds 3× the direct
                # A→B distance the result is a circumnavigation, not a reroute.
                direct_dist = geod.Inverse(a[1], a[0], b[1], b[0])["s12"]
                total_route = sum(
                    geod.Inverse(
                        sub_coords[k][1], sub_coords[k][0],
                        sub_coords[k + 1][1], sub_coords[k + 1][0]
                    )["s12"]
                    for k in range(len(sub_coords) - 1)
                )
                if total_route <= direct_dist * 3:
                    # Normalize antimeridian continuity relative to point 'a'
                    normalized = _normalize_antimeridian(sub_coords[1:], a[0])
                    return normalized
    except RouteBusy:
        raise
    except Exception:
        pass

    # Strategy 2: perpendicular-offset midpoint detour
    geod = Geodesic.WGS84
    try:
        inv = geod.Inverse(a[1], a[0], b[1], b[0])
        bearing = inv["azi1"]
        dist = inv["s12"]
        mid_line = geod.InverseLine(a[1], a[0], b[1], b[0])

        # Adaptive offset distances: use finer steps for short segments so the
        # detour stays close enough to navigate narrow island channels/passages
        # (e.g. the approach to Pointe-à-Pitre around Basse-Terre, ~32km).
        if dist < 100_000:
            detour_distances_km = [10, 20, 30, 50]
        else:
            detour_distances_km = [50, 100, 150, 200]

        for frac in [0.5, 0.33, 0.67]:
            mid_pos = mid_line.Position(frac * dist)
            mid_lat, mid_lon = mid_pos["lat2"], mid_pos["lon2"]

            for sign in [1, -1]:          # try both sides of the segment
                for detour_km in detour_distances_km:
                    p = geod.Direct(
                        mid_lat, mid_lon,
                        (bearing + sign * 90) % 360,
                        detour_km * 1000
                    )
                    wp = [p["lon2"], p["lat2"]]
                    # Normalize the detour waypoint longitude for continuity
                    wp = _normalize_antimeridian([wp], a[0])[0]
                    if _is_land_hires(wp[1], wp[0]):
                        continue          # detour point itself is on land
                    seg1_ok = not _segment_crosses_land(a[0], a[1], wp[0], wp[1])
                    seg2_ok = not _segment_crosses_land(wp[0], wp[1], b[0], b[1])
                    if seg1_ok and seg2_ok:
                        # Also normalize b relative to the detour waypoint
                        b_norm = _normalize_antimeridian([b], wp[0])[0]
                        return [wp, b_norm]    # clean two-leg detour found
    except Exception:
        pass

    return [b]   # last-resort direct hop


def _segment_enters(lon1: float, lat1: float, lon2: float, lat2: float,
                    inside, n_samples: int = 30, _folded: bool = False) -> bool:
    """Vrai si la géodésique traverse une zone interdite (deux échantillons de suite).

    Un port situé dans un parc est déjà retiré du test par l'appelant
    (escape_points). On ne masque donc ni le début ni la fin du segment :
    un sommet intermédiaire posé dans l'aire compterait sinon comme une
    simple sortie. Un segment qui traverse ±180° est coupé
    (split_antimeridian) et chaque morceau replié est contrôlé : le saut
    de longitude seul ne dispense plus du contrôle.
    """
    if inside is None:
        return False
    if not _folded:
        pieces = split_antimeridian(lon1, lat1, lon2, lat2)
        if len(pieces) > 1:
            return any(
                _segment_enters(p_lon1, p_lat1, p_lon2, p_lat2, inside, n_samples, True)
                for p_lon1, p_lat1, p_lon2, p_lat2 in pieces
            )
        lon1, lat1, lon2, lat2 = pieces[0]
    try:
        line = Geodesic.WGS84.InverseLine(lat1, lon1, lat2, lon2)
        total = line.s13
    except Exception:
        return False
    if total < 1000:
        return False
    consecutive = 0
    try:
        for k in range(1, n_samples):
            pos = line.Position(k / n_samples * total)
            if inside(pos["lat2"], pos["lon2"]):
                consecutive += 1
                if consecutive >= 2:
                    return True
            else:
                consecutive = 0
    except Exception:
        return False
    return False


def _detour_clear(a: list, b: list, inside) -> list:
    """Remplace A→B par un détour hors terre et hors zone interdite.

    Retourne les points après A, B compris. [B] si aucun détour ne convient.
    """
    geod = Geodesic.WGS84
    try:
        inv = geod.Inverse(a[1], a[0], b[1], b[0])
        line = geod.InverseLine(a[1], a[0], b[1], b[0])
    except Exception:
        return [b]
    bearing, dist = inv["azi1"], inv["s12"]
    # Une aire peut être plus large que la jambe qui la coupe (réserve de
    # ~100 km sur un segment de 70 km). Le palier court ne la contourne pas.
    if inside is not None:
        distances = [5, 10, 20, 40, 80, 120, 180, 260]
    elif dist < 100_000:
        distances = [2, 4, 8, 12, 20, 30, 40]
    else:
        distances = [5, 10, 20, 40, 80, 120, 180]
    for frac in (0.5, 0.33, 0.67, 0.25, 0.75):
        mid = line.Position(frac * dist)
        for sign in (1, -1):
            for km in distances:
                p = geod.Direct(mid["lat2"], mid["lon2"], (bearing + sign * 90) % 360, km * 1000)
                wp = _normalize_antimeridian([[p["lon2"], p["lat2"]]], a[0])[0]
                if _is_land_hires(wp[1], wp[0]):
                    continue
                if inside is not None:
                    try:
                        if inside(wp[1], wp[0]):
                            continue
                    except Exception:
                        continue
                if _segment_crosses_land(a[0], a[1], wp[0], wp[1]):
                    continue
                if _segment_crosses_land(wp[0], wp[1], b[0], b[1]):
                    continue
                if inside is not None and (
                    _segment_enters(a[0], a[1], wp[0], wp[1], inside)
                    or _segment_enters(wp[0], wp[1], b[0], b[1], inside)
                ):
                    continue
                b_norm = _normalize_antimeridian([b], wp[0])[0]
                return [wp, b_norm]
    if dist < 40_000:
        return _nearby_water_detour(a, b, inside)
    return [b]


def _nearby_water_detour(a: list, b: list, inside, radius: float = 0.35, step: float = 0.02) -> list:
    """Pour une sortie de port : le premier point d'eau dont les deux bouts sont libres."""
    geod = Geodesic.WGS84
    mid_lat = (a[1] + b[1]) / 2
    mid_lon = (a[0] + b[0]) / 2
    best = None
    best_m = float("inf")
    n = int(radius / step)
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            lat = mid_lat + i * step
            lon = mid_lon + j * step
            if _is_land_hires(lat, lon):
                continue
            if inside is not None:
                try:
                    if inside(lat, lon):
                        continue
                except Exception:
                    continue
            if _segment_crosses_land(a[0], a[1], lon, lat):
                continue
            if _segment_crosses_land(lon, lat, b[0], b[1]):
                continue
            if inside is not None and (
                _segment_enters(a[0], a[1], lon, lat, inside)
                or _segment_enters(lon, lat, b[0], b[1], inside)
            ):
                continue
            extra = (
                geod.Inverse(a[1], a[0], lat, lon)["s12"]
                + geod.Inverse(lat, lon, b[1], b[0])["s12"]
            )
            if extra < best_m:
                best_m = extra
                best = [lon, lat]
    if best is None:
        return [b]
    b_norm = _normalize_antimeridian([b], best[0])[0]
    return [_normalize_antimeridian([best], a[0])[0], b_norm]


def _snap_out_of_zone(lon: float, lat: float, inside, max_km: float = 160.0) -> list:
    """Ramène un sommet posé dans une zone interdite sur l'eau, juste dehors.

    Le premier point d'eau libre le plus proche, par anneaux. Si rien n'est
    libre dans le rayon, le sommet ne bouge pas.
    """
    try:
        if not inside(lat, lon):
            return [lon, lat]
    except Exception:
        return [lon, lat]
    geod = Geodesic.WGS84
    for km in (4, 8, 12, 20, 30, 45, 60, 80, 110, 150):
        if km > max_km:
            break
        for bearing in range(0, 360, 15):
            p = geod.Direct(lat, lon, bearing, km * 1000)
            plat, plon = p["lat2"], p["lon2"]
            if _is_land_hires(plat, plon):
                continue
            try:
                if inside(plat, plon):
                    continue
            except Exception:
                continue
            return _normalize_antimeridian([[plon, plat]], lon)[0]
    return [lon, lat]


def route_open_hits(coords: list, inside) -> list:
    """Segments encore dans la terre ou dans une aire interdite.

    Un hit par segment : ``land`` et ``area`` disent pourquoi. ``inside``
    est le prédicat d'aire ``(lat, lon) -> bool``, ou None s'il n'y a pas
    de catalogue. La liste vide veut dire que le dernier détour a laissé
    la ligne dehors.
    """
    hits: list = []
    if not coords or len(coords) < 2:
        return hits
    for i in range(len(coords) - 1):
        a, b = coords[i], coords[i + 1]
        if not a or not b or len(a) < 2 or len(b) < 2:
            continue
        try:
            land = _segment_crosses_land(float(a[0]), float(a[1]), float(b[0]), float(b[1]))
        except Exception:
            land = False
        area = False
        if inside is not None:
            try:
                area = _segment_enters(float(a[0]), float(a[1]), float(b[0]), float(b[1]), inside)
            except Exception:
                area = False
        if land or area:
            hits.append({
                "index": i,
                "from": [a[0], a[1]],
                "to": [b[0], b[1]],
                "land": bool(land),
                "area": bool(area),
            })
    return hits


def avoid_zones(coords: list, inside=None, max_iterations: int = 4) -> list:
    """Détourne les segments qui traversent encore la terre ou une zone interdite."""
    if not coords or len(coords) < 2:
        return coords
    if inside is not None and len(coords) >= 3:
        # Les bouts de la jambe restent (escales). Un sommet du milieu tombé
        # dans l'aire est sorti avant le détour, sinon chaque branche repart
        # de l'intérieur et le test la compte encore comme une traversée.
        snapped = [coords[0]]
        for pt in coords[1:-1]:
            snapped.append(_snap_out_of_zone(pt[0], pt[1], inside))
        snapped.append(coords[-1])
        coords = snapped
    for _ in range(max_iterations):
        changed = False
        result = [coords[0]]
        for i in range(len(coords) - 1):
            a = result[-1]
            b = coords[i + 1]
            land = _segment_crosses_land(a[0], a[1], b[0], b[1])
            forbidden = inside is not None and _segment_enters(a[0], a[1], b[0], b[1], inside)
            if land or forbidden:
                detour = _detour_clear(a, b, inside)
                if len(detour) > 1:
                    result.extend(detour)
                    changed = True
                    continue
            result.append(b)
        coords = result
        if not changed:
            break
    return coords


def _split_canal_links(coords: list) -> list:
    """Coupe en deux un lien de passage nommé plus long que 60 km.

    Hors des boîtes Panama et Suez, un segment n'est plus découpé parce
    qu'il mesure 20 à 40 km : 28 km de terre qui n'est pas un canal nommé
    reste une traversée. Dans une boîte, un lien au-delà de 60 km peut
    être coupé en son milieu, seulement si ce milieu reste dans la boîte.
    """
    if len(coords) < 2:
        return coords
    geod = Geodesic.WGS84
    result = [coords[0]]
    for i in range(len(coords) - 1):
        a = result[-1]
        b = coords[i + 1]
        if not _segment_crosses_land(a[0], a[1], b[0], b[1]):
            result.append(b)
            continue
        try:
            box = _shared_passage_box(float(a[0]), float(a[1]), float(b[0]), float(b[1]))
        except (TypeError, ValueError):
            result.append(b)
            continue
        if box is None:
            result.append(b)
            continue
        try:
            line = geod.InverseLine(a[1], a[0], b[1], b[0])
            dist = float(line.s13)
        except Exception:
            result.append(b)
            continue
        if not math.isfinite(dist) or dist <= NAMED_PASSAGE_MAX_M:
            result.append(b)
            continue
        midpos = line.Position(dist / 2)
        mid_lon, mid_lat = float(midpos["lon2"]), float(midpos["lat2"])
        if not in_passage_box(wrap_lon(mid_lon), mid_lat, box):
            result.append(b)
            continue
        mid = _normalize_antimeridian([[mid_lon, mid_lat]], a[0])[0]
        b_norm = _normalize_antimeridian([b], mid[0])[0]
        left_clear = not _segment_crosses_land(a[0], a[1], mid[0], mid[1])
        right_clear = not _segment_crosses_land(mid[0], mid[1], b_norm[0], b_norm[1])
        if left_clear and right_clear:
            result.extend([mid, b_norm])
        else:
            result.append(b)
    return result


def _forbidden_amp_predicate(start, end):
    """Un seul prédicat d'aire interdite à la plaisance, ou None.

    None si le catalogue est vide ou si le chargement lève : l'appelant
    pose ``ampStatus = unavailable`` et ne fait pas semblant d'avoir
    vérifié. Les aires à circulation régulée ne font pas partie de ce
    prédicat : ``amp_nogo`` ne garde que l'interdit plaisance.
    """
    try:
        from amp_nogo import amp_nogo_fn, load_forbidden_nogo
        items = load_forbidden_nogo()
        if not items:
            return None
        return amp_nogo_fn(
            items,
            escape_points=[(float(start[1]), float(start[0])), (float(end[1]), float(end[0]))],
        )
    except Exception:
        return None


def avoid_forbidden_amps(coords: list, start, end, inside=None) -> list:
    """Détourne les aires interdites à la plaisance. Sans catalogue, la ligne ne bouge pas.

    ``inside`` est le prédicat déjà construit pour ce calcul. None : catalogue
    vide ou en panne, on ne recharge pas et on ne détourne pas.
    """
    if inside is None:
        return coords
    return avoid_zones(coords, inside)


def _stamp_avoidance_status(props: dict, coords: list, inside) -> None:
    """After the last detour. Does not raise: the tracer receives the line and status.

    Missing catalogue: ``ampStatus = unavailable`` AND ``constraintStatus = fail`` (fail-closed).
    Catalogue present and a segment still inside the area: ``constraintStatus = open``.
    A land hit alone does not mark the area as open.
    """
    if inside is None:
        props["ampStatus"] = "unavailable"
        props["constraintStatus"] = "fail"
        return
    try:
        hits = route_open_hits(coords, inside)
    except Exception:
        props["ampStatus"] = "unavailable"
        return
    if any(hit.get("area") for hit in hits):
        props["constraintStatus"] = "open"


def avoid_land(coords: list, max_iterations: int = 8, deadline: float | None = None) -> list:
    """
    Iteratively scan every consecutive segment in the route and reroute
    any that cross land, until the route is fully clean or max_iterations
    is reached.

    This is the core "Avoid Land" function: it guarantees that the rendered
    polyline never crosses a landmass or island as long as a detour can be
    found within the search parameters of _find_land_crossing_detour.
    """
    if not _LAND_MASK_AVAILABLE and _NE_TREE is None:
        return coords

    for iteration in range(max_iterations):
        changed = False
        result = [coords[0]]

        for i in range(len(coords) - 1):
            a = result[-1]
            b = coords[i + 1]

            if _segment_crosses_land(a[0], a[1], b[0], b[1]):
                detour = _find_land_crossing_detour(a, b, deadline)
                result.extend(detour)
                changed = True
            else:
                result.append(b)

        coords = result
        if not changed:
            print(f"✅ avoid_land: clean after {iteration + 1} iteration(s), {len(coords)} waypoints")
            break
    else:
        print(f"⚠️  avoid_land: max_iterations={max_iterations} reached, {len(coords)} waypoints")

    return coords


def _snap_to_ocean(lat: float, lon: float, max_radius_deg: float = 1.5) -> Optional[list]:
    """
    Given a point classified as land, find and return the nearest ocean cell
    whose centre lies STRICTLY within max_radius_deg of (lat, lon), using
    the 1/4° grid spacing of global_land_mask.

    Returns [lon, lat] of the nearest qualifying ocean cell, or None.
    """
    if not _LAND_MASK_AVAILABLE:
        return [lon, lat]

    grid = 0.25   # 1/4° matches global_land_mask resolution
    steps = int(max_radius_deg / grid) + 1
    max_sq = max_radius_deg ** 2        # strict radius² cut-off
    best_pt: Optional[list] = None
    best_dist_sq = float("inf")

    for di in range(-steps, steps + 1):
        for dj in range(-steps, steps + 1):
            dist_sq = (di * grid) ** 2 + (dj * grid) ** 2
            if dist_sq > max_sq:
                continue   # outside the requested radius
            if dist_sq >= best_dist_sq:
                continue   # already have a closer candidate
            try:
                tlat = lat + di * grid
                tlon = lon + dj * grid
                if not _globe.is_land(tlat, tlon):
                    best_pt = [tlon, tlat]
                    best_dist_sq = dist_sq
            except Exception:
                pass

    return best_pt


def _snap_to_ocean_fine(lat: float, lon: float,
                         radius_deg: float = 0.15,
                         grid: float = 0.01) -> Optional[list]:
    """
    High-resolution version of _snap_to_ocean.

    Searches for the nearest ocean point within *radius_deg* of (lat, lon)
    using a fine *grid* step (default 0.01° ≈ 1 km).  Uses the combined
    high-resolution land check (_is_land_hires) — Natural Earth 1:10m +
    global_land_mask — so it correctly resolves small-island harbours and
    narrow channels that the coarse 1/4° grid misses.

    Returns [lon, lat] of the closest water cell, or None if none found.
    """
    geod = Geodesic.WGS84
    steps = int(radius_deg / grid) + 1
    max_sq = radius_deg ** 2

    best_pt: Optional[list] = None
    best_dist_m = float("inf")

    for di in range(-steps, steps + 1):
        for dj in range(-steps, steps + 1):
            dist_sq = (di * grid) ** 2 + (dj * grid) ** 2
            if dist_sq > max_sq:
                continue                      # outside search radius
            tlat = lat + di * grid
            tlon = lon + dj * grid
            if _is_land_hires(tlat, tlon):
                continue                      # still on land
            dist_m = geod.Inverse(lat, lon, tlat, tlon)["s12"]
            if dist_m < best_dist_m:
                best_dist_m = dist_m
                best_pt = [tlon, tlat]

    return best_pt


def _densify_coords(coords: list, max_km: float = 75.0) -> list:
    """
    Insert geodesic intermediate waypoints so that no consecutive pair is
    further apart than max_km.  This prevents the map renderer (MapLibre)
    from drawing a straight line that visually crosses a landmass between
    two ocean waypoints.

    Antimeridian wrapping is preserved.
    """
    geod = Geodesic.WGS84
    max_m = max_km * 1000.0
    result = [coords[0]]

    for i in range(len(coords) - 1):
        a, b = coords[i], coords[i + 1]
        try:
            line = geod.InverseLine(a[1], a[0], b[1], b[0])
            dist = line.s13
            if dist > max_m:
                n = int(dist / max_m) + 1
                for j in range(1, n):
                    pos = line.Position(j / n * dist)
                    # keep antimeridian continuity
                    lon = unwrap_lon(result[-1][0], pos["lon2"])
                    result.append([lon, pos["lat2"]])
        except Exception:
            pass
        result.append(b)

    return result


def _sanitize_route_coords(coords: list) -> list:
    """
    Ensure every intermediate waypoint lies in the ocean:

    • Ocean cells                           → kept exactly as-is.
    • Land cells with ocean within 0.5°     → snapped to that ocean cell.
      (coastal nodes slightly inside a land cell at 1/4° resolution)
    • Land cells with ocean only within 1.5° → kept as-is.
      (narrow maritime passages: Suez Canal, Panama Canal, straits —
       the nearest ocean is the distant sea, NOT a nearby lake; the node
       is still a valid routing guide through the passage)
    • Land cells with no ocean within 1.5°  → dropped (genuinely inland).

    First and last points (departure / destination ports) are always kept
    unchanged — ships dock at coasts.
    """
    if not _LAND_MASK_AVAILABLE and _NE_TREE is None:
        return coords

    cleaned = [coords[0]]   # always keep departure

    for i in range(1, len(coords) - 1):
        lon, lat = coords[i]
        on_land = _is_land_hires(lat, lon)

        if not on_land:
            cleaned.append(coords[i])                    # ocean → keep
        else:
            # tight snap ≤ 0.3° (one grid cell) — catches coastal clips only.
            # Canal/strait nodes are typically 0.35°+ from open water so they
            # don't qualify here and fall through to the passage-keep rule.
            snapped = _snap_to_ocean(lat, lon, max_radius_deg=0.3)
            if snapped:
                cleaned.append(snapped)                  # coastal clip → snap
            elif _has_nearby_ocean(lat, lon, radius_deg=1.5):
                cleaned.append(coords[i])               # canal/passage → keep as-is
            # else: genuinely inland → drop silently

    cleaned.append(coords[-1])  # always keep destination
    return cleaned


# à augmenter quand le pipeline change.
# 2 : deux changements depuis 429c1e3 (recontrôle des aires, puis canaux nommés).
ENGINE_REV = 2


def _catalog_id_fingerprint(items: list) -> str:
    """Hash sha256 des identifiants d'aires triés. Les géométries n'entrent pas.

    Un identifiant vide est ignoré. Les doublons ne comptent qu'une fois.
    La liste vide a un hash : ce n'est pas le mot « unavailable ».
    """
    seen: set[str] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("id") or "").strip()
        if text:
            seen.add(text)
    payload = "\n".join(sorted(seen))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _area_catalog_fingerprint() -> str:
    """Empreinte du catalogue courant, ou « unavailable » s'il ne se charge pas.

    Un catalogue chargé et vide a le hash de zéro identifiant. Ce hash ne
    se confond pas avec la panne : une ligne calculée sans catalogue ne
    doit pas être resservie une fois le catalogue vide connu, ni l'inverse.
    """
    try:
        from amp_nogo import forbidden_catalog_available, load_forbidden_nogo
        items = load_forbidden_nogo()
        if forbidden_catalog_available() is not True:
            return "unavailable"
    except Exception:
        return "unavailable"
    return _catalog_id_fingerprint(list(items or []))


def _route_cache_key(start, end, *, catalog_fp: str | None = None) -> tuple:
    """
    Bidirectional cache key: always places the lexicographically smaller point
    first so that A→B and B→A map to the same key.
    Coordinates are rounded to 4 decimal places (~11 m precision) so that
    floating-point noise doesn't create spurious cache misses.

    The key also carries ENGINE_REV and the area-catalog fingerprint, so a
    line computed before an avoidance change, or with another catalog, is
    not served again. ``catalog_fp`` None reads the live catalog.
    """
    p1 = (round(start[0], 4), round(start[1], 4))
    p2 = (round(end[0], 4), round(end[1], 4))
    fp = _area_catalog_fingerprint() if catalog_fp is None else catalog_fp
    return (ENGINE_REV, min(p1, p2), max(p1, p2), fp)


# In-memory route cache  {cache_key: (route_dict, canonical_start_tuple)}
# The canonical_start is whichever endpoint was used as start when the route
# was first computed; the cache consumer flips the coordinate list when the
# request goes in the opposite direction.
_route_cache: dict = {}


def endpoint_on_land(lat: float, lon: float) -> bool:
    """Terre franche : pas un port, pas une rade (océan à moins de ~0,35°)."""
    if not _LAND_MASK_AVAILABLE and _NE_TREE is None:
        return False
    try:
        y = float(lat)
        x = float(wrap_lon(lon))
    except (TypeError, ValueError):
        return False
    if not _is_land_hires(y, x):
        return False
    return not _has_nearby_ocean(y, x, radius_deg=0.35)


def segment_crosses_land(lon1: float, lat1: float, lon2: float, lat2: float) -> bool:
    return _segment_crosses_land(lon1, lat1, lon2, lat2)


# Un seul essai, borné à ~8 s. Searoute tourne dans un process enfant, tué à
# l'échéance (searoute_worker) : aucun calcul ne continue après le délai.
SEAROUTE_TIMEOUT_S = 8.0
# The whole /route request (searoute, then the detours around land). Longer
# than one searoute call: measured on an Apple M2 with warm workers, La
# Rochelle → Nouméa takes about 3.1 s and La Rochelle → Papeete 2.5 s
# (searoute then avoid_land); a slower or busier server (CI, four parallel
# legs) needs that margin before answering 503.
ROUTE_DEADLINE_S = 12.0
SEAROUTE_TARGET = "searoute:searoute"


def _invoke_searoute(start, end, timeout_s: float | None = None):
    """searoute's answer, or None. None after a time-out, a full pool or a dead
    worker also flags `_SEAROUTE_BUSY`, so the caller can tell « busy » from
    « searoute found no route »."""
    from searoute_worker import RUNNER, TIMED_OUT, WorkerDied

    if timeout_s is None:
        timeout_s = SEAROUTE_TIMEOUT_S
    try:
        route = RUNNER.run(SEAROUTE_TARGET, (list(start), list(end)), timeout_s)
    except WorkerDied as exc:
        print(f"⚠️ searoute worker: {exc}")
        _SEAROUTE_BUSY.set(True)
        return None
    except Exception as exc:
        print(f"⚠️ Erreur searoute: {exc}")
        return None
    if route is TIMED_OUT:
        print("⚠️ searoute timeout")
        _SEAROUTE_BUSY.set(True)
        return None
    return route


def route_length_km(coords: list) -> float:
    """Geodesic length of the final polyline (unfolded lon are fine)."""
    geod = Geodesic.WGS84
    total = 0.0
    for p, q in zip(coords, coords[1:]):
        total += geod.Inverse(p[1], p[0], q[1], q[0])["s12"]
    return total / 1000.0


def searoute_with_exact_end(start, end, deadline: float | None = None):
    """
    Calcule une route maritime entre deux points et ajoute un segment géodésique
    jusqu'à la destination exacte si searoute s'arrête trop tôt.
    Gère correctement le passage de l'antiméridien (180°/-180°).

    Bidirectional cache: if the reverse segment B→A was already computed, the
    cached coordinate list is reversed and returned immediately — ensuring that
    the aller and retour legs between the same two waypoints render as a single
    identical line on the map.
    """
    import copy

    # searoute attend [−180, 180] ; une lon dépliée (SF à 236,84°) partait au Béring.
    start = (wrap_lon(start[0]), start[1])
    end = (wrap_lon(end[0]), end[1])

    cache_key = _route_cache_key(start, end)
    canonical_start = (round(start[0], 4), round(start[1], 4))

    if cache_key in _route_cache:
        cached_route, cached_canonical_start = _route_cache[cache_key]
        route = copy.deepcopy(cached_route)
        # If this request goes in the opposite direction, reverse the coords
        if canonical_start != cached_canonical_start:
            route["geometry"]["coordinates"].reverse()
        return attach_anti_shipping(route)

    if deadline is None:
        deadline = time.monotonic() + ROUTE_DEADLINE_S
    left = _time_left(deadline)
    if left <= 0:
        raise RouteBusy("route deadline reached")
    token = _SEAROUTE_BUSY.set(False)
    try:
        route = _invoke_searoute(start, end, min(SEAROUTE_TIMEOUT_S, left))
        busy = _SEAROUTE_BUSY.get()
    finally:
        _SEAROUTE_BUSY.reset(token)
    if busy:
        raise RouteBusy("searoute did not answer in time")

    if not route or "geometry" not in route:
        return None

    coords = route["geometry"]["coordinates"]

    geod = Geodesic.WGS84

    # ── Exact start: prepend the origin if searoute snapped to a different node ──
    first_point = coords[0]
    start_dist = geod.Inverse(start[1], start[0], first_point[1], first_point[0])["s12"]
    if start_dist > 1000:
        coords.insert(0, [start[0], start[1]])

    last_point = coords[-1]
    dist = geod.Inverse(last_point[1], last_point[0], end[1], end[0])["s12"]

    if dist > 1000:
        # Append the exact endpoint as a single segment — avoid_land will insert
        # detour waypoints as needed.  Pre-interpolating with many 5 km sub-points
        # previously caused problems: each tiny sub-segment crossing a large island
        # (e.g. Basse-Terre / Guadeloupe) could not be individually rerouted, leading
        # to an oscillating zigzag that never converged.
        line = geod.InverseLine(last_point[1], last_point[0], end[1], end[0])
        pos = line.Position(line.s13)
        lat = pos["lat2"]
        # Antimeridian normalisation relative to the preceding point
        lon = unwrap_lon(coords[-1][0], pos["lon2"])
        coords.append([lon, lat])

    # ── Avoid-Land Pipeline ─────────────────────────────────────────────────

    # Step 1 — initial avoid-land pass: iteratively reroute every segment
    #           that crosses any landmass or island (major coasts, peninsulas,
    #           small islands like Nias / Mentawai).
    coords = avoid_land(coords, deadline=deadline)

    # Step 2 — densify: insert intermediate waypoints so no segment exceeds
    #           75 km, preventing the renderer from drawing a chord that
    #           visually crosses land between two distant ocean points.
    coords = _densify_coords(coords, max_km=75)

    # Step 3 — per-point cleanup: snap coastal clips to the nearest ocean
    #           cell, preserve canal / strait passage nodes, drop inland stray
    #           points introduced by earlier steps.
    coords = _sanitize_route_coords(coords)

    # Step 4 — second avoid-land pass: densification in Step 2 can place new
    #           geodesic midpoints on small islands (e.g. Nias).  This final
    #           iterative scan catches and reroutes any remaining crossings.
    coords = avoid_land(coords, max_iterations=5, deadline=deadline)

    # Un seul prédicat d'aire pour les deux passages. Le détour de terre qui
    # suit le premier peut reposer le trait dans l'aire : le dernier
    # avoid_zones reprend ce même prédicat. Les aires régulées ne sont pas
    # un mur. Sans catalogue, la ligne de terre est rendue quand même.
    inside = _forbidden_amp_predicate(start, end)
    try:
        coords = avoid_forbidden_amps(coords, start, end, inside)
    except RouteBusy:
        raise
    except Exception:
        inside = None
    coords = avoid_land(coords, max_iterations=3, deadline=deadline)
    if inside is None:
        coords = avoid_zones(coords)
    else:
        try:
            coords = avoid_zones(coords, inside)
        except RouteBusy:
            raise
        except Exception:
            inside = None
    coords = _split_canal_links(coords)

    # Continu relativement au départ replié : pas de saut ±360° entre deux sommets.
    coords = _normalize_antimeridian(coords, start[0])
    route["geometry"]["coordinates"] = coords
    # searoute's length is for its own line: the exact ends and the detours
    # changed it. The length cached and served is the one drawn.
    props = dict(route.get("properties") or {})
    props["length"] = round(route_length_km(coords), 3)
    props["units"] = "km"
    # Recontrôle sur la ligne rendue, après le dernier détour. Pas d'exception :
    # GET /route doit livrer le trait et le statut.
    _stamp_avoidance_status(props, coords, inside)
    route["properties"] = props
    attach_anti_shipping(route)

    # Store in bidirectional cache so the reverse leg reuses this result
    lru_set(_route_cache, cache_key, (copy.deepcopy(route), canonical_start),
            max_items=ROUTE_CACHE_MAX)

    return route


