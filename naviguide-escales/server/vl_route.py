"""Points de la route Berry-Mappemonde et propositions d'ids (job vl_route_bm).

Plan sans réseau : escales, entrées et sorties de ZEE/AMP lues dans le stock
officiel du poste s'il est là, échantillons de longues jambes. Une image
locale par point, dessinée depuis la géométrie de ``public/route.geojson``.

Les tuiles du fond de carte affiché par l'appli ne sont pas téléchargées :
leur licence interdit de les remettre à un modèle. L'image envoyée est ce
dessin local. L'appel au modèle n'a lieu que dans ``execute``, lancé plus
tard par ``scripts/one_shot.py --run``. Les tests injectent une réponse.
Un id hors du sac est rejeté. Aucune phrase de la réponse n'entre dans le récit.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
import unicodedata
import zlib
from pathlib import Path
from typing import Any, Callable

from longitude import delta_lon, unwrap_lon, wrap_lon

JOB = "vl_route_bm"
REV = "vb1"
TIER = "write"
# Estimation locale d'un appel (texte du sac + image), pas un chiffre du modèle.
PROMPT_TOKENS = 416
COMPLETION_TOKENS = 64
MAX_IMAGES = 36
MAX_CROSSINGS = 12
MAX_SAMPLES_PER_LEG = 2
LONG_LEG_NM = 800.0
SAMPLE_EVERY_NM = 2500.0
_AIR_JUMP_NM = 120.0
_OFF_ROUTE_NM = 80.0
_NEAR_ESCALE_NM = 8.0
TILE_ZOOM = 5
TILE_SPAN = 2
_R_NM = 3440.065
_IMAGE = 96

# Catalogue Token Factory. L'hôte et la clef restent ceux de story_cascade :
# infra/agents/vl_film_review.py n'est pas dans cet arbre.
_VL_MODEL = "nvidia/Nemotron-3.5-Super-VL"
_VL_MODEL_ENV = "NAVIGUIDE_TF_MODEL_VL"

_PREFIX = {
    "escale": "e",
    "zee-enter": "zi",
    "zee-exit": "zo",
    "amp-enter": "ai",
    "amp-exit": "ao",
    "leg": "l",
}
_ROLE_RANK = {"escale": 0, "zee-enter": 1, "zee-exit": 1, "amp-enter": 2, "amp-exit": 2, "leg": 3}
_CALL_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_HAUTE_RE = re.compile(r"haute mer", re.I)
_SORTIE_RE = re.compile(r"sortie\b", re.I)

_TRANSPORT: Callable[[bytes, list[str]], str] | None = None
_BAG_PROVIDER: Callable[[dict], list[str]] | None = None
_TRACK_CACHE: tuple[list[dict], list[dict]] | None = None


def vl_model() -> str:
    raw = (os.environ.get(_VL_MODEL_ENV) or "").strip()
    return raw or _VL_MODEL


def set_transport(fn: Callable[[bytes, list[str]], str] | None) -> None:
    """Réponse factice. ``None`` rétablit l'appel réel, réservé à ``--run``."""
    global _TRANSPORT
    _TRANSPORT = fn


def set_bag_provider(fn: Callable[[dict], list[str]] | None) -> None:
    global _BAG_PROVIDER
    _BAG_PROVIDER = fn


def _nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = p2 - p1
    dlon = math.radians(delta_lon(lon1, lon2))
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * _R_NM * math.asin(min(1.0, math.sqrt(a)))


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _route_path() -> Path:
    return Path(__file__).resolve().parent.parent / "public" / "route.geojson"


def official_track() -> tuple[list[dict], list[dict]]:
    """Trace et escales de la route officielle embarquée. Aucun réseau."""
    global _TRACK_CACHE
    if _TRACK_CACHE is not None:
        return _TRACK_CACHE
    try:
        fc = json.loads(_route_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _TRACK_CACHE = ([], [])
        return _TRACK_CACHE
    segments: list[list] = []
    stops: list[dict] = []
    for feat in fc.get("features") or []:
        if not isinstance(feat, dict):
            continue
        geom = feat.get("geometry") if isinstance(feat.get("geometry"), dict) else {}
        props = feat.get("properties") if isinstance(feat.get("properties"), dict) else {}
        coords = geom.get("coordinates") or []
        if geom.get("type") == "LineString" and len(coords) >= 2:
            segments.append(coords)
        elif (
            geom.get("type") == "Point"
            and len(coords) >= 2
            and props.get("point_type") == "escale"
        ):
            lon, lat = _float(coords[0]), _float(coords[1])
            name = str(props.get("name") or "").strip()
            if lon is None or lat is None or not name:
                continue
            stops.append({"name": name, "lon": lon, "lat": lat})
    points: list[dict] = []
    cum = 0.0

    def add(lon: float, lat: float, *, jump: bool) -> None:
        nonlocal cum
        if points:
            lon = unwrap_lon(points[-1]["lon"], lon)
            prev = points[-1]
            if abs(prev["lat"] - lat) < 1e-9 and abs(prev["lon"] - lon) < 1e-6:
                return
            if not jump:
                cum += _nm(prev["lat"], prev["lon"], lat, lon)
        points.append({"lat": lat, "lon": lon, "cumNm": cum, "jump": jump})

    for coords in segments:
        start = 0
        if points:
            lon0, lat0 = _float(coords[0][0]), _float(coords[0][1])
            if lon0 is None or lat0 is None:
                continue
            prev = points[-1]
            if _nm(prev["lat"], prev["lon"], lat0, lon0) >= _AIR_JUMP_NM:
                add(lon0, lat0, jump=True)
                start = 1
        for pair in coords[start:]:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            lon, lat = _float(pair[0]), _float(pair[1])
            if lon is None or lat is None:
                continue
            add(lon, lat, jump=False)
    marks: list[dict] = []
    search = 0
    for stop in stops:
        best, best_d = search, 1e18
        for i in range(search, len(points)):
            dist = _nm(stop["lat"], stop["lon"], points[i]["lat"], points[i]["lon"])
            if dist < best_d:
                best, best_d = i, dist
        if not points:
            continue
        pt = points[best]
        marks.append({
            "name": stop["name"],
            "lat": stop["lat"],
            "lon": stop["lon"],
            "nm": pt["cumNm"],
            "index": best,
        })
        search = best
    _TRACK_CACHE = (points, marks)
    return _TRACK_CACHE


def route_stamp() -> str:
    _points, marks = official_track()
    bits = [f"{m.get('name')}|{round(float(m.get('nm') or 0), 1)}" for m in marks]
    return hashlib.sha256("\n".join(bits).encode("utf-8")).hexdigest()[:16]


def crossing_role(change: dict) -> str | None:
    """Entrée ou sortie telle que le journal la note. Rien n'est inventé."""
    if not isinstance(change, dict):
        return None
    kind = str(change.get("kind") or "")
    event = str(change.get("event") or "").lower()
    title = str(change.get("title") or "")
    fact = str(change.get("fact") or "")
    leaving = (
        event in {"exit", "leave"}
        or bool(_HAUTE_RE.search(title))
        or bool(_SORTIE_RE.match(fact.strip()))
    )
    blob = f"{title} {fact}"
    if kind == "zee-enter" or (kind == "zee" and event in {"enter", "exit", "entry", "leave"}):
        if re.search(r"ports? d['’]entr|formalit", blob, re.I):
            return None
        return "zee-exit" if leaving else "zee-enter"
    if kind == "amp":
        try:
            from film_script import alert_is_amp  # noqa: PLC0415
        except Exception:
            return None
        if not alert_is_amp(change):
            return None
        return "amp-exit" if leaving else "amp-enter"
    if kind not in {"alert-on", "alert-off"}:
        return None
    try:
        from film_script import alert_is_amp  # noqa: PLC0415
    except Exception:
        return None
    if not alert_is_amp(change):
        return None
    if kind == "alert-off" or leaving:
        return "amp-exit"
    return "amp-enter"


def crossings_from_moments(moments: list | None) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple] = set()
    for row in moments or []:
        if not isinstance(row, dict):
            continue
        pos = row.get("pos") if isinstance(row.get("pos"), dict) else {}
        lat = _float(pos.get("lat") if pos.get("lat") is not None else row.get("lat"))
        lon = _float(pos.get("lon") if pos.get("lon") is not None else row.get("lon"))
        if lat is None or lon is None:
            continue
        for change in row.get("changes") or []:
            if not isinstance(change, dict):
                continue
            role = crossing_role(change)
            if not role:
                continue
            key = (role, round(lat, 1), round(lon, 1))
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "role": role,
                "lat": lat,
                "lon": lon,
                "name": str(change.get("title") or change.get("name") or role),
            })
    return out


def _store_probe_allowed() -> bool:
    if (os.environ.get("NAVIGUIDE_OFFICIAL_STORE_DIR") or "").strip():
        return True
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("CI"):
        return False
    return True


def local_crossings() -> list[dict]:
    """Croisements déjà dans le stock du poste. Pas de téléchargement."""
    if not _store_probe_allowed():
        return []
    try:
        from official_store import official_journal_moments  # noqa: PLC0415
        return crossings_from_moments(official_journal_moments())
    except Exception:
        return []


def _nearest(track: list[dict], lat: float, lon: float) -> tuple[int, float]:
    best_i, best_d = 0, 1e18
    for i, pt in enumerate(track):
        dist = _nm(lat, lon, pt["lat"], pt["lon"])
        if dist < best_d:
            best_i, best_d = i, dist
    return best_i, best_d


def _thin(rows: list[dict], cap: int) -> list[dict]:
    ordered = sorted(rows, key=lambda r: float(r.get("nm") or 0))
    if cap <= 0 or not ordered:
        return []
    if len(ordered) <= cap:
        return ordered
    if cap == 1:
        return [ordered[len(ordered) // 2]]
    step = (len(ordered) - 1) / (cap - 1)
    picked: list[dict] = []
    used: set[int] = set()
    for i in range(cap):
        idx = int(round(i * step))
        if idx in used or idx >= len(ordered):
            continue
        used.add(idx)
        picked.append(ordered[idx])
    return picked


def _leg_samples(track: list[dict], marks: list[dict]) -> list[dict]:
    samples: list[dict] = []
    for left, right in zip(marks, marks[1:]):
        i0, i1 = int(left["index"]), int(right["index"])
        if i1 <= i0:
            continue
        if any(track[k].get("jump") for k in range(i0 + 1, i1 + 1)):
            continue
        dist = float(right["nm"]) - float(left["nm"])
        if dist < LONG_LEG_NM:
            continue
        count = min(MAX_SAMPLES_PER_LEG, max(1, int(dist // SAMPLE_EVERY_NM)))
        for k in range(1, count + 1):
            target = float(left["nm"]) + dist * k / (count + 1)
            best = None
            best_d = 1e18
            for pt in track[i0 + 1:i1]:
                gap = abs(float(pt["cumNm"]) - target)
                if gap < best_d:
                    best, best_d = pt, gap
            if best is None:
                continue
            if abs(float(best["cumNm"]) - float(left["nm"])) < 40:
                continue
            if abs(float(right["nm"]) - float(best["cumNm"])) < 40:
                continue
            samples.append({
                "role": "leg",
                "name": "leg",
                "lat": best["lat"],
                "lon": best["lon"],
                "nm": best["cumNm"],
            })
    return samples


def _slug(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (text[:36] or "point")


def select_key_points(
    track: list[dict],
    marks: list[dict],
    crossings: list[dict] | None = None,
) -> list[dict]:
    """Escales, croisements bornés, échantillons de longues jambes. Plafond fixe."""
    escales: list[dict] = []
    for mark in marks:
        lat, lon, nm = _float(mark.get("lat")), _float(mark.get("lon")), _float(mark.get("nm"))
        name = str(mark.get("name") or "").strip()
        if lat is None or lon is None or nm is None or not name:
            continue
        escales.append({"role": "escale", "name": name, "lat": lat, "lon": lon, "nm": nm})
    placed: list[dict] = []
    for row in crossings or []:
        lat, lon = _float(row.get("lat")), _float(row.get("lon"))
        role = str(row.get("role") or "")
        if lat is None or lon is None or role not in _PREFIX or not track:
            continue
        _idx, dist = _nearest(track, lat, lon)
        if dist > _OFF_ROUTE_NM:
            continue
        nm = float(track[_idx]["cumNm"])
        if any(abs(nm - float(esc["nm"])) < _NEAR_ESCALE_NM for esc in escales):
            continue
        placed.append({
            "role": role,
            "name": str(row.get("name") or role),
            "lat": lat,
            "lon": lon,
            "nm": nm,
        })
    kept = _thin(placed, min(MAX_CROSSINGS, max(0, MAX_IMAGES - len(escales))))
    room = MAX_IMAGES - len(escales) - len(kept)
    legs = _thin(_leg_samples(track, marks), room) if room > 0 else []
    chosen = escales + kept + legs
    chosen.sort(key=lambda p: (float(p["nm"]), _ROLE_RANK.get(p["role"], 9), p["name"]))
    if len(chosen) > MAX_IMAGES:
        chosen = [p for p in chosen if p["role"] == "escale"][:MAX_IMAGES]
    out: list[dict] = []
    for i, point in enumerate(chosen, start=1):
        call_id = f"{_PREFIX[point['role']]}{i:03d}-{_slug(point['name'])}"[:64]
        if not _CALL_ID.fullmatch(call_id):
            call_id = f"{_PREFIX[point['role']]}{i:03d}-point"
        out.append({**point, "callId": call_id})
    return out


def key_points(*, crossings: list[dict] | None = None) -> list[dict]:
    track, marks = official_track()
    if crossings is None:
        crossings = local_crossings()
    return select_key_points(track, marks, crossings)


def tile_refs(lat: float, lon: float, z: int = TILE_ZOOM, span: int = TILE_SPAN) -> list[dict]:
    """Indices des tuiles que la carte montrerait. Aucune n'est demandée."""
    lat = max(-85.05112878, min(85.05112878, lat))
    lon = wrap_lon(lon)
    n = 2 ** z
    x = min(n - 1, max(0, int((lon + 180.0) / 360.0 * n)))
    lat_r = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n)
    y = min(n - 1, max(0, y))
    half = span // 2
    refs: list[dict] = []
    for dy in range(span):
        for dx in range(span):
            refs.append({
                "z": z,
                "x": (x - half + dx) % n,
                "y": min(n - 1, max(0, y - half + dy)),
            })
    return refs


def describe(points: list[dict] | None = None) -> dict[str, Any]:
    pts = key_points() if points is None else points
    roles: dict[str, int] = {}
    for point in pts:
        roles[point["role"]] = roles.get(point["role"], 0) + 1
    n = len(pts)
    return {
        "points": n,
        "images": n,
        "calls": n,
        "tiles": n * TILE_SPAN * TILE_SPAN,
        "tilesFetched": 0,
        "roles": roles,
    }


def format_account(points: list[dict] | None = None) -> str:
    info = describe(points)
    roles = " ".join(f"{key}={info['roles'][key]}" for key in sorted(info["roles"]))
    lines = [
        f"points: {info['points']}",
        f"images: {info['images']}",
        f"calls: {info['calls']}",
        f"tiles: {info['tiles']}",
        f"tiles_fetched: {info['tilesFetched']}",
        f"roles: {roles}",
    ]
    return "\n".join(lines) + "\n"


def _store_root() -> Path | None:
    env = (os.environ.get("NAVIGUIDE_OFFICIAL_STORE_DIR") or "").strip()
    if env:
        return Path(env)
    try:
        import official_store  # noqa: PLC0415
    except Exception:
        return None
    inst = getattr(official_store, "_INSTANCE", None)
    if inst is not None:
        root = getattr(getattr(inst, "backend", None), "root", None)
        if root is not None:
            return Path(root)
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("CI"):
        return None
    return official_store.DEFAULT_DISK


def result_path(*, mkdir: bool = False) -> Path | None:
    root = _store_root()
    if root is None:
        return None
    path = Path(root) / "vl-route" / f"{REV}.json"
    if mkdir:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load() -> dict | None:
    path = result_path()
    if path is None or not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def save(doc: dict) -> None:
    path = result_path(mkdir=True)
    if path is None:
        raise OSError("stock officiel indisponible")
    payload = json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def ids_for_bag(bag: list[dict] | None) -> list[str]:
    """Ids du cache déjà dans le sac, dans l'ordre enregistré. Cache absent : []."""
    try:
        doc = load()
        if not isinstance(doc, dict) or doc.get("rev") != REV:
            return []
        if doc.get("route") != route_stamp():
            return []
        allowed = {
            str(item.get("id"))
            for item in bag or []
            if isinstance(item, dict) and item.get("id")
        }
        out: list[str] = []
        seen: set[str] = set()
        for raw in doc.get("ids") or []:
            sid = str(raw)
            if sid in allowed and sid not in seen:
                seen.add(sid)
                out.append(sid)
        return out
    except Exception:
        return []


def _json_obj(text: str) -> dict | None:
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def _clean_reason(text: str) -> str:
    """Raison courte. Une phrase qui porte un nombre absent des faits est jetée."""
    from story_cascade import filter_numbers  # noqa: PLC0415

    kept, _dropped = filter_numbers(text or "", "")
    kept = " ".join(kept.split())
    if any(ch.isdigit() for ch in kept):
        return ""
    if len(kept) > 80:
        kept = kept[:80].rsplit(" ", 1)[0].strip()
    return kept


def parse_response(text: str, allowed: set[str] | list[str]) -> list[dict]:
    """JSON d'ids du sac, ordre conservé. Id inconnu rejeté. Pas de prose."""
    data = _json_obj(text)
    if not data:
        return []
    raw_ids = data.get("ids")
    if not isinstance(raw_ids, list):
        return []
    reasons = data.get("reasons") if isinstance(data.get("reasons"), dict) else {}
    allow = {str(item) for item in allowed}
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw_ids:
        reason = ""
        if isinstance(item, dict):
            sid = str(item.get("id") or "")
            reason = str(item.get("reason") or "")
        else:
            sid = str(item)
            if sid in reasons:
                reason = str(reasons.get(sid) or "")
        if sid not in allow or sid in seen:
            continue
        seen.add(sid)
        out.append({"id": sid, "reason": _clean_reason(reason)})
    return out


def _science_is_buoy(item: dict) -> bool:
    """Même type que le film : une bouée du sac, pas un titre de jeu."""
    from ici_engine import science_type_key  # noqa: PLC0415

    return science_type_key(item) == "buoy"


def ids_from_ici_bag(bag: dict | None) -> list[str]:
    """Familles réellement présentes dans le sac du point, ids du film."""
    if not isinstance(bag, dict):
        return []
    ids: list[str] = []

    def add(kind: str) -> None:
        sid = f"dc:{kind}"
        if sid not in ids:
            ids.append(sid)

    amps = bag.get("amp") if isinstance(bag.get("amp"), list) else []
    for area in amps:
        if not isinstance(area, dict) or not (area.get("name") or area.get("title")):
            continue
        label = f"{area.get('designation') or ''} {area.get('name') or ''}".lower()
        if "fisher" in label or "pêche" in label or "peche" in label or "pétoncle" in label:
            continue
        add("amp")
        break
    science = bag.get("science") if isinstance(bag.get("science"), dict) else {}
    for item in science.get("nearby") or []:
        if isinstance(item, dict) and _science_is_buoy(item):
            add("buoy")
            break
    poe = bag.get("poe") if isinstance(bag.get("poe"), list) else []
    if any(isinstance(row, dict) and (row.get("name") or row.get("title")) for row in poe):
        add("poe")
    nearby = bag.get("nearby") if isinstance(bag.get("nearby"), dict) else {}
    anchors = bag.get("anchorages")
    if nearby.get("marinas") or (isinstance(anchors, list) and anchors):
        add("anchorage")
    aton = bag.get("aton") if isinstance(bag.get("aton"), dict) else {}
    if aton.get("nearby"):
        add("aton")
    emo = bag.get("emodnet") if isinstance(bag.get("emodnet"), dict) else {}
    cables = emo.get("cables") if isinstance(emo.get("cables"), dict) else {}
    if cables.get("name"):
        add("cable")
    bathy = emo.get("bathy") if isinstance(emo.get("bathy"), dict) else {}
    if bag.get("depthOffshore") is not None or bathy.get("depth_m") is not None:
        add("depth")
    piracy = bag.get("piracy") if isinstance(bag.get("piracy"), dict) else {}
    if piracy.get("name"):
        add("piracy")
    sat = bag.get("satellites") if isinstance(bag.get("satellites"), dict) else {}
    if sat.get("scene") or sat.get("caption"):
        add("satellite")
    return ids


def bag_ids_for(point: dict) -> list[str]:
    if _BAG_PROVIDER is not None:
        return [str(item) for item in _BAG_PROVIDER(point) if str(item)]
    if not _store_probe_allowed():
        return []
    try:
        from official_store import ici_bag_near  # noqa: PLC0415
        bag = ici_bag_near(float(point["lat"]), float(point["lon"]))
    except Exception:
        return []
    return ids_from_ici_bag(bag)


def _set_px(buf: bytearray, width: int, height: int, x: int, y: int, color: bytes) -> None:
    if 0 <= x < width and 0 <= y < height:
        i = (y * width + x) * 3
        buf[i:i + 3] = color


def _line(buf: bytearray, width: int, height: int, x0: int, y0: int, x1: int, y1: int, color: bytes) -> None:
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        _set_px(buf, width, height, x0, y0, color)
        if x0 == x1 and y0 == y1:
            break
        doubled = 2 * err
        if doubled >= dy:
            err += dy
            x0 += sx
        if doubled <= dx:
            err += dx
            y0 += sy


def render_png(point: dict, track: list[dict] | None = None) -> bytes:
    """Schéma local autour du point. Pas une tuile tierce."""
    if track is None:
        track, _marks = official_track()
    ref_lon = float(point["lon"])
    ref_lat = float(point["lat"])
    window = []
    for pt in track:
        if abs(pt["lat"] - ref_lat) <= 12 and abs(delta_lon(ref_lon, pt["lon"])) <= 12:
            window.append(pt)
    if not window:
        window = [{"lat": ref_lat, "lon": ref_lon}]
    lats = [pt["lat"] for pt in window] + [ref_lat]
    lons = [ref_lon + delta_lon(ref_lon, pt["lon"]) for pt in window] + [ref_lon]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    if max_lat - min_lat < 0.4:
        min_lat -= 0.2
        max_lat += 0.2
    if max_lon - min_lon < 0.4:
        min_lon -= 0.2
        max_lon += 0.2
    span_lat = max_lat - min_lat
    span_lon = max_lon - min_lon
    width = height = _IMAGE
    buf = bytearray(bytes((14, 23, 38)) * (width * height))
    ink = bytes((226, 232, 240))
    mark = bytes((248, 250, 252))

    def xy(lat: float, lon: float) -> tuple[int, int]:
        rel = ref_lon + delta_lon(ref_lon, lon)
        x = int((rel - min_lon) / span_lon * (width - 8) + 4)
        y = int((max_lat - lat) / span_lat * (height - 8) + 4)
        return x, y

    prev = None
    for pt in window:
        cur = xy(pt["lat"], pt["lon"])
        if prev is not None and not pt.get("jump"):
            _line(buf, width, height, prev[0], prev[1], cur[0], cur[1], ink)
        prev = cur
    cx, cy = xy(ref_lat, ref_lon)
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            if dx * dx + dy * dy <= 4:
                _set_px(buf, width, height, cx + dx, cy + dy, mark)
    return _png(width, height, buf)


def _png(width: int, height: int, rgb: bytearray) -> bytes:
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        raw.extend(rgb[y * stride:(y + 1) * stride])

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def _upsert(point: dict, rows: list[dict]) -> dict:
    doc = load()
    stamp = route_stamp()
    if not isinstance(doc, dict) or doc.get("rev") != REV or doc.get("route") != stamp:
        doc = {"rev": REV, "route": stamp, "job": JOB, "points": [], "ids": []}
    points = [row for row in doc.get("points") or [] if row.get("callId") != point["callId"]]
    points.append({
        "callId": point["callId"],
        "role": point["role"],
        "name": point.get("name") or "",
        "nm": point["nm"],
        "lat": point["lat"],
        "lon": point["lon"],
        "ids": [row["id"] for row in rows],
        "reasons": {row["id"]: row["reason"] for row in rows if row.get("reason")},
    })
    points.sort(key=lambda row: (float(row.get("nm") or 0), str(row.get("callId"))))
    ids: list[str] = []
    seen: set[str] = set()
    for row in points:
        for sid in row.get("ids") or []:
            if sid not in seen:
                seen.add(sid)
                ids.append(sid)
    doc["points"] = points
    doc["ids"] = ids
    doc["rev"] = REV
    doc["route"] = stamp
    doc["job"] = JOB
    save(doc)
    return doc


def _call_vl(png: bytes, ids: list[str]) -> str:
    """Appel Token Factory. Interdit sous pytest et si le mode LLM est coupé."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise RuntimeError("appel réel interdit pendant les tests")
    import httpx  # noqa: PLC0415
    import llm_budget  # noqa: PLC0415
    import story_cascade  # noqa: PLC0415

    if not llm_budget.llm_allowed_here(TIER):
        raise RuntimeError("appel refusé")
    key = story_cascade.nebius_key()
    if not key:
        raise RuntimeError("clef absente")
    import base64  # noqa: PLC0415

    system = (
        "You select ids from the given bag for one point of a sailing route. "
        "Return JSON only: {\"ids\":[...], \"reasons\":{\"id\":\"short\"}}. "
        "Choose only among the given ids. Do not write a narrative sentence. "
        "Do not invent a number or a name."
    )
    user_text = json.dumps({"ids": ids}, ensure_ascii=True, separators=(",", ":"))
    payload = {
        "model": vl_model(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode("ascii")}},
            ]},
        ],
        "max_tokens": COMPLETION_TOKENS,
        "temperature": 0,
        "stream": False,
        "reasoning_effort": "none",
        "chat_template_kwargs": {"enable_thinking": False},
    }
    try:
        with httpx.Client(timeout=story_cascade.TIMEOUT) as client:
            response = client.post(
                story_cascade._tf_url(TIER),
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
            )
    except httpx.HTTPError:
        raise RuntimeError("appel VL interrompu")
    if response.status_code >= 400:
        raise story_cascade._http_error("tokenfactory", response)
    data = response.json()
    text = story_cascade._openai_text(data)
    # Réponse vide (raisonnement seul, finish_reason=length) : déjà facturée.
    prompt_tokens, completion_tokens = story_cascade._usage_tokens(data, system, user_text, text)
    llm_budget.record(TIER, prompt_tokens, completion_tokens)
    if not text:
        raise RuntimeError("réponse vide")
    return text


def _dispatch(png: bytes, ids: list[str]) -> str:
    if _TRANSPORT is not None:
        return _TRANSPORT(png, ids)
    return _call_vl(png, ids)


def execute_call(call: Any) -> dict[str, Any]:
    """Un point : image locale, sac, réponse. Sac vide : aucun appel."""
    point = next((row for row in key_points() if row["callId"] == call.call_id), None)
    if point is None:
        raise KeyError(call.call_id)
    png = render_png(point)
    allowed = bag_ids_for(point)
    rows: list[dict] = []
    if allowed:
        rows = parse_response(_dispatch(png, allowed), allowed)
    _upsert(point, rows)
    return {"id": call.call_id, "ids": [row["id"] for row in rows]}


def estimate_extra() -> str:
    """Points, images, tuiles non téléchargées. Déjà hors de l'empreinte."""
    info = describe()
    roles = " ".join(f"{key}={info['roles'][key]}" for key in sorted(info["roles"]))
    lines = [
        f"points: {info['points']}",
        f"images: {info['images']}",
        f"tiles_fetched: {info['tilesFetched']}",
        f"roles: {roles}",
    ]
    return "\n".join(lines) + "\n"


def plan_calls() -> list[Any]:
    import one_shot  # noqa: PLC0415

    return [
        one_shot.PlannedCall(point["callId"], TIER, PROMPT_TOKENS, COMPLETION_TOKENS)
        for point in key_points()
    ]


def register_job() -> None:
    import one_shot  # noqa: PLC0415

    if JOB in one_shot.REGISTRY:
        return
    one_shot.register(one_shot.Job(JOB, plan_calls, execute_call, estimate_extra))
