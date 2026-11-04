"""API voyage — bateau virtuel (Simulation B), port 8010."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from admin_guard import is_admin, rate_limited, require_admin
from climatology_atlas import corridor_cells, prefetch_atlas_cells
from forecast_blend import FORECAST_BLEND_END_HOURS, make_wind_fn
from hindcast import ERA5_PRODUCTS, at as hindcast_at
from hindcast import fill_era5_along, hindcast_enabled, hindcast_status_fields
from hindcast import om_quota_blocked, past_passage_slots, uncovered_era5_slots
from forecast_cube import (
    CACHE_TTL_H,
    CUBE_MAX_BYTES,
    build_voyage_cube,
    load_cube,
    save_cube,
)
from amp_nogo import amp_nogo_fn, load_forbidden_nogo
from isochrone import WAVE_NOGO_M, combine_nogo, haversine, run_leg_isochrone, skipper_nogo
from longitude import delta_lon, unwrap_lon as _unwrap_lon
from grib_fetch import is_stale, maybe_refresh_official
from saildocs import (
    DAILY_RADIUS_NM,
    GRIB_MISSING,
    GRIB_PRODUCTS,
    absent_payload,
    dest_eta_at_next_download,
    ingest_daily,
    last_ready_cycle,
    load_latest,
    public_grib,
    saildocs_queries,
    saildocs_query,
    scan_inbox,
    track_from_clock,
    utc_day,
    wind_at_daily,
)
from voyage_clock import (
    OFFICIAL_T0,
    OFFICIAL_VOYAGE_ID,
    build_voyage_clock,
    official_clock_params,
    parse_iso,
    sample_clock_at_time,
    to_iso,
)
from voyage_store import load_voyage, purge_stale_voyages, save_voyage, update_voyage
from weather_pipeline import ProcessJob, get_async_weather_queue, get_pipeline
import voyage_journal as journal
import official_store

log = logging.getLogger("naviguide-simulator.voyage")
router = APIRouter()

# /recompute: how long the atlas warm-up may take before the isochrone starts.
ATLAS_PREFETCH_BUDGET_S = 6.0

# Sécurité P0 — bornes d'un voyage de Simulation (la route Berry complète fait
# ~1 500 points) et limiteurs par IP. L'admin (X-Naviguide-Admin) est exempté.
MAX_VOYAGE_POINTS = 6000
MAX_VOYAGE_MARKS = 300
STALE_VOYAGE_DAYS = 7
# Itinéraire Berry embarqué. public/route.geojson est un lien vers
# backend/data/route.geojson (source unique, dépôt Blue Intelligence),
# le même fichier que le client charge en /route.geojson. Après la
# séparation, NAVIGUIDE remplace ce lien par le fichier récupéré
# depuis GET /api/export/route.geojson. Pas une seconde copie ici.
# Seule exception : la recette hors ligne (NAVIGUIDE_OFFLINE, posé par
# scripts/e2e-store-api.sh) lit la route sur laquelle le stock figé a été
# calculé (NAVIGUIDE_OFFICIAL_ROUTE_FILE), pour que l'empreinte de la route
# corresponde aux clés de l'archive. Jamais en production ni en dev.
_PUBLIC_ROUTE_GEOJSON = Path(__file__).resolve().parent.parent / "public" / "route.geojson"


def _route_geojson_path() -> Path:
    override = (os.environ.get("NAVIGUIDE_OFFICIAL_ROUTE_FILE") or "").strip()
    if override:
        import offline  # noqa: PLC0415

        if offline.enabled():
            return Path(override)
    return _PUBLIC_ROUTE_GEOJSON


_ROUTE_GEOJSON = _route_geojson_path()
_AIR_JUMP_NM = 120.0
_AIR_FILM_NM = 80.0
_create_limited = rate_limited("voyage-create", 6, 60.0, global_limit=60)
_compute_limited = rate_limited("voyage-compute", 6, 60.0, global_limit=40)
_official_read_limited = rate_limited("official-read", 240, 60.0)

try:
    from polar_api import _load_polar_data
except Exception:  # pragma: no cover
    _load_polar_data = None


class VoyageCreate(BaseModel):
    t0: str
    expedition_id: str = "berry-mappemonde-2026"
    routeKind: str = "berry"
    follow: bool = True
    forecast: bool = True
    startAt: str = "la-rochelle"
    official: bool = False
    points: List[Dict[str, Any]]
    marks: List[Dict[str, Any]] = Field(default_factory=list)


_OFFICIAL_BODY_CACHE: Optional[VoyageCreate] = None


class RecomputeBody(BaseModel):
    to_name: Optional[str] = None
    t: Optional[str] = None
    # Les ordres du skipper comme contraintes du routage (conseil de route).
    wind_max_kt: Optional[float] = None
    hs_max_m: Optional[float] = None


class DailyGribIn(BaseModel):
    model: str = "GFS"
    source: str = "saildocs"
    day: Optional[str] = None
    issued: Optional[str] = None
    around: Optional[Dict[str, Any]] = None
    bbox: Optional[List[float]] = None
    radiusNm: float = DAILY_RADIUS_NM
    samples: List[Dict[str, Any]] = Field(default_factory=list)
    query: Optional[str] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _polar_raw(expedition_id: str) -> Optional[dict]:
    if not _load_polar_data:
        return None
    try:
        polar = _load_polar_data(expedition_id)
        return {
            "twa_rows": list(polar.twa_rows),
            "tws_cols": list(polar.tws_cols),
            "matrix": polar.matrix.tolist(),
        }
    except Exception:
        return None


def _climo_clock(voy: dict) -> dict:
    return build_voyage_clock(
        voy.get("points") or [],
        voy.get("marks") or [],
        voy["t0"],
        polar_raw=_polar_raw(voy.get("expedition_id") or ""),
        start_at=voy.get("startAt") or "la-rochelle",
        wind_fn=None,
    )


def _hindcast_lookup(lat: float, lon: float, t: datetime):
    """Vent du passé : ERA5 Open-Meteo uniquement (Copernicus = bonus, jamais bloquant)."""
    if not hindcast_enabled():
        return None
    try:
        return hindcast_at(lat, lon, t, products=ERA5_PRODUCTS, fetch=False)
    except Exception:
        return None


def _clock_with_cube(voy: dict, cube) -> dict:
    t0 = parse_iso(voy["t0"])
    now = _now()
    return build_voyage_clock(
        voy.get("points") or [],
        voy.get("marks") or [],
        t0,
        polar_raw=_polar_raw(voy.get("expedition_id") or ""),
        start_at=voy.get("startAt") or "la-rochelle",
        wind_fn=make_wind_fn(t0, cube, now=now, hindcast_fn=_hindcast_lookup),
    )


def _prefetch_hindcast(voy: dict, now: datetime) -> int:
    """ERA5 le long du trait déjà parcouru (dates du clock courant). Pas de Copernicus."""
    if not hindcast_enabled():
        return 0
    clock = voy.get("clock") or _climo_clock(voy)
    slots = past_passage_slots(clock, now)
    if len(slots) > 800:
        slots = slots[:800]
    try:
        return fill_era5_along(slots)
    except Exception as exc:
        log.info("hindcast prefetch: %s", exc)
        return 0


def _fill_hindcast_then_forecast(voyage_id: str) -> None:
    voy = load_voyage(voyage_id)
    if voy is None:
        return
    now = _now()
    try:
        obtained = 0
        if hindcast_enabled() and not om_quota_blocked():
            obtained += _prefetch_hindcast(voy, now)
        t0 = parse_iso(voy["t0"])
        live_nm = 0.0
        clock = voy.get("clock")
        if clock:
            sample = sample_clock_at_time(clock, now)
            if sample:
                live_nm = float(sample.get("sailNm") or 0)
        cube = build_voyage_cube(voy.get("points") or [], t0, from_sail_nm=live_nm)
        if cube.estimate_bytes() > CUBE_MAX_BYTES:
            log.warning("cube trop gros (%s o), on réduit", cube.estimate_bytes())
            cube.samples = cube.samples[: max(4, len(cube.samples) // 2)]
        save_cube(voyage_id, cube)
        clock = _clock_with_cube(voy, cube)
        if hindcast_enabled() and not om_quota_blocked():
            missing = uncovered_era5_slots(clock, now)
            if missing:
                obtained += fill_era5_along(missing[:800])
                clock = _clock_with_cube(voy, cube)
        extra = {}
        if hindcast_enabled():
            extra.update(hindcast_status_fields(clock, now, obtained=obtained > 0))
        else:
            extra["hindcastStatus"] = "skipped"
        update_voyage(
            voyage_id,
            forecastStatus="ready",
            forecastModel=cube.model,
            waveModel=cube.wave_model,
            cubeBytes=cube.estimate_bytes(),
            forecastRefreshedAt=to_iso(now),
            clock=clock,
            **extra,
        )
        _journal_safely(lambda: journal.record_wx_from_hindcast(clock, now))
    except Exception as exc:
        log.warning("hindcast/prévision indisponible pour %s: %s", voyage_id, exc)
        voy = load_voyage(voyage_id) or voy
        climo = voy.get("clock") or _climo_clock(voy)
        if climo.get("kind") != "climatology":
            climo = {**climo, "kind": "climatology"}
        update_voyage(
            voyage_id,
            forecastStatus="unavailable",
            hindcastStatus="unavailable",
            forecastModel=None,
            clock=climo,
        )


def _fill_forecast(voyage_id: str) -> None:
    """Alias C2 : hindcast puis prévision."""
    _fill_hindcast_then_forecast(voyage_id)


def _is_official(voyage_id: str) -> bool:
    return voyage_id == OFFICIAL_VOYAGE_ID


def _journal_safely(fn) -> None:
    """Le journal ne casse jamais une lecture publique."""
    try:
        fn()
    except Exception as exc:  # defensive
        log.warning("journal officiel: %s", exc)


def _coord_num(value: Any) -> float:
    """Nombre fini. 1 et 1.0 sont la même coordonnée ; -0.0 vaut 0.0."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError
    if number == 0.0:
        return 0.0
    return number


def _pairs_fingerprint(pairs: list[tuple[float, float]]) -> str:
    """SHA-256 hex des couples [lon, lat], ordre conservé.

    Mêmes coordonnées, même ordre → même empreinte. Les noms de jambes,
    les milles et le t0 n'entrent pas : le fichier et le voyage se comparent.
    """
    raw = json.dumps(
        [[lon, lat] for lon, lat in pairs],
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def route_points_fingerprint(points) -> Optional[str]:
    """Empreinte des points stockés. None s'il n'y a pas de liste lisible."""
    if not points:
        return None
    pairs: list[tuple[float, float]] = []
    for point in points:
        if not isinstance(point, dict):
            return None
        try:
            pairs.append((_coord_num(point["lon"]), _coord_num(point["lat"])))
        except (KeyError, TypeError, ValueError):
            return None
    if not pairs:
        return None
    return _pairs_fingerprint(pairs)


_FILE_FP_CACHE: Optional[tuple[int, int, Optional[str]]] = None


def route_file_fingerprint() -> Optional[str]:
    """Empreinte des LineString de public/route.geojson. Lecture seule."""
    global _FILE_FP_CACHE
    try:
        stat = _ROUTE_GEOJSON.stat()
    except OSError:
        return None
    stamp = (stat.st_mtime_ns, stat.st_size)
    if (
        _FILE_FP_CACHE is not None
        and _FILE_FP_CACHE[0] == stamp[0]
        and _FILE_FP_CACHE[1] == stamp[1]
    ):
        return _FILE_FP_CACHE[2]
    fingerprint: Optional[str] = None
    try:
        from route_contract import line_strings  # noqa: PLC0415

        collection = json.loads(_ROUTE_GEOJSON.read_text(encoding="utf-8"))
        pairs: list[tuple[float, float]] = []
        for line in line_strings(collection):
            for coord in line.get("coordinates") or []:
                if not isinstance(coord, (list, tuple)) or len(coord) < 2:
                    continue
                pairs.append((_coord_num(coord[0]), _coord_num(coord[1])))
        if pairs:
            fingerprint = _pairs_fingerprint(pairs)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        log.warning("empreinte du fichier de route illisible: %s", exc)
        fingerprint = None
    _FILE_FP_CACHE = (stamp[0], stamp[1], fingerprint)
    return fingerprint


def _public_meta(voy: dict) -> dict:
    official = voy.get("official") or _is_official(voy.get("voyageId") or "")
    meta = {
        "voyageId": voy["voyageId"],
        "t0": voy["t0"],
        "expedition_id": voy.get("expedition_id"),
        "routeKind": voy.get("routeKind"),
        "routeRev": voy.get("routeRev", 0),
        "follow": voy.get("follow", True),
        "official": official,
        "forecastStatus": voy.get("forecastStatus"),
        "hindcastStatus": voy.get("hindcastStatus"),
        "hindcastCoverage": voy.get("hindcastCoverage"),
        "hindcastReason": voy.get("hindcastReason"),
        "forecastModel": voy.get("forecastModel"),
        "waveModel": voy.get("waveModel"),
        "startAt": voy.get("startAt"),
        "cubeBytes": voy.get("cubeBytes"),
        "forecastRefreshedAt": voy.get("forecastRefreshedAt"),
        "hindcastRefreshedAt": voy.get("hindcastRefreshedAt"),
        "disclaimer": {
            "notForNav": "Ne convient pas à la navigation.",
        },
    }
    if official:
        # Lecture du fichier et des points déjà en mémoire. Aucune écriture.
        meta["routeFileFp"] = route_file_fingerprint()
        meta["routeVoyageFp"] = route_points_fingerprint(voy.get("points"))
    return meta


def _dated_error(reason: str, status: str = "unavailable") -> dict:
    """Erreur propre (jamais une stack avalée) : statut, raison lisible, horodatage UTC."""
    return {"status": status, "reason": str(reason), "at": to_iso(_now())}


def _clock_has_vertices(clock) -> bool:
    return isinstance(clock, dict) and bool(clock.get("vertices"))


def _preparing_clock_body(voy: dict, reason: str) -> dict:
    """Même contrat que l'officiel preparing : daté, sans sommets inventés."""
    body = _dated_error(reason, "preparing")
    t0 = voy.get("t0")
    if t0:
        body = {"t0": t0, **body}
    return body


def _official_clock_from_store(voy: Optional[dict] = None) -> Optional[dict]:
    """Horloge officielle : stock RF2, sinon celle déjà posée sur le voyage. Jamais un calcul."""
    clock = official_store.stored_clock()
    if isinstance(clock, dict) and clock.get("t0"):
        return clock
    stored = (voy or {}).get("clock")
    if isinstance(stored, dict) and stored.get("t0"):
        return stored
    return None


def _normalized_t0(raw: str) -> str:
    return to_iso(parse_iso(raw))


def _same_t0(a: str, b: str) -> bool:
    try:
        return parse_iso(a) == parse_iso(b)
    except Exception:
        return False


def _route_fp(points, marks, t0: str) -> str:
    """Empreinte RF2 (points + marques + t0). Le t0 est déjà normalisé."""
    return official_store.route_fingerprint({
        "t0": t0,
        "points": points or [],
        "marks": marks or [],
        "routeRev": 0,
    })


def _official_route_fp() -> Optional[str]:
    """Empreinte du voyage officiel chargé, sinon celle de l'itinéraire Berry."""
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    if voy and voy.get("points"):
        raw = voy.get("t0") or OFFICIAL_T0
        try:
            t0 = _normalized_t0(raw)
        except Exception:
            t0 = OFFICIAL_T0
        return _route_fp(voy.get("points"), voy.get("marks"), t0)
    itinerary = official_itinerary_body()
    if itinerary and itinerary.points:
        return _route_fp(itinerary.points, itinerary.marks, OFFICIAL_T0)
    return None


def _matches_official_request(body: VoyageCreate) -> bool:
    """official:true, ou même t0 officiel + même empreinte de route."""
    if body.official:
        return True
    if not _same_t0(body.t0, OFFICIAL_T0):
        return False
    official_fp = _official_route_fp()
    if not official_fp:
        return False
    try:
        t0 = _normalized_t0(body.t0)
    except Exception:
        return False
    return _route_fp(body.points, body.marks, t0) == official_fp


def _flag_marks(marks: List[dict]) -> List[dict]:
    out = []
    for m in marks or []:
        name = str(m.get("name") or "")
        if m.get("flag") is False:
            continue
        out.append(m)
    return out


def _next_flag(marks: List[dict], sail_nm: float, to_name: Optional[str] = None) -> Optional[dict]:
    ordered = sorted(marks or [], key=lambda m: float(m.get("nm") or m.get("filmNm") or 0))
    if to_name:
        for m in ordered:
            if to_name.lower() in str(m.get("name") or "").lower():
                return m
    for m in ordered:
        nm = float(m.get("nm") or m.get("filmNm") or 0)
        if nm > sail_nm + 1:
            return m
    return ordered[-1] if ordered else None


def _leg_coords(points: List[dict], from_nm: float, to_nm: float) -> List[tuple]:
    coords = []
    for p in points or []:
        nm = float(p.get("cumNm") or 0)
        if from_nm - 0.5 <= nm <= to_nm + 0.5 and not p.get("jump"):
            coords.append((p["lat"], p["lon"]))
    return coords


def _recompute_cum(points: List[dict]) -> List[dict]:
    out = []
    cum = 0.0
    film = 0.0
    prev = None
    for p in points:
        q = dict(p)
        if prev is not None:
            if q.get("jump"):
                film += 80.0
            else:
                d = haversine(prev["lat"], prev["lon"], q["lat"], q["lon"])
                cum += d
                film += d
        q["cumNm"] = round(cum, 4)
        q["filmCum"] = round(film, 4)
        out.append(q)
        prev = q
    return out


def _splice_points(points: List[dict], from_nm: float, to_nm: float,
                   new_coords: List[List[float]]) -> List[dict]:
    """new_coords = [lon, lat]. Amont inchangé, jambe remplacée, aval intact."""
    before = [p for p in points if float(p.get("cumNm") or 0) < from_nm - 0.05]
    after = [p for p in points if float(p.get("cumNm") or 0) > to_nm + 0.05]
    mid = []
    for lon, lat in new_coords:
        mid.append({"lat": lat, "lon": lon, "jump": False, "nonMaritime": False})
    return _recompute_cum(before + mid + after)


# Écart officiel vs recalcul (règles) puis phrase tier fast.
AVOID_NM = 10.0
ADVICE_SYSTEM = (
    "Tu expliques un recalcul de route en UNE phrase. "
    "Tu ne produis aucun chiffre qui n'est pas déjà dans les faits. "
    "Reprend l'écart et les points évités. Thinking OFF."
)


def _run_async(coro):
    return asyncio.run(coro)


def route_delta(
    old_coords: List[List[float]] | None,
    new_coords: List[List[float]] | None,
    *,
    official_nm: float | None,
    recomputed_nm: float | None,
) -> dict[str, Any]:
    """Distance, écart max et points évités — calculés par règles, jamais par un LLM.

    Coordonnées GeoJSON `[lon, lat]`. Un point officiel est « évité » s'il
    reste à ≥ AVOID_NM nm de tout sommet de la route recalculée.
    """
    old = [(float(c[1]), float(c[0])) for c in (old_coords or []) if c and len(c) >= 2]
    new = [(float(c[1]), float(c[0])) for c in (new_coords or []) if c and len(c) >= 2]
    max_dev = 0.0
    avoided = 0
    if old and new:
        for la, lo in old:
            d = min(haversine(la, lo, na, no) for na, no in new)
            if d > max_dev:
                max_dev = d
            if d >= AVOID_NM:
                avoided += 1
    off = int(round(float(official_nm or 0)))
    rec = int(round(float(recomputed_nm or 0)))
    return {
        "official_nm": off,
        "recomputed_nm": rec,
        "distance_delta_nm": abs(rec - off),
        "max_deviation_nm": int(round(max_dev)),
        "avoided_points": int(avoided),
    }


def advice_facts(delta: dict[str, Any], constraints: dict[str, Any] | None = None) -> dict[str, Any]:
    facts = {
        "official_nm": delta.get("official_nm"),
        "recomputed_nm": delta.get("recomputed_nm"),
        "distance_delta_nm": delta.get("distance_delta_nm"),
        "max_deviation_nm": delta.get("max_deviation_nm"),
        "avoided_points": delta.get("avoided_points"),
    }
    cons = constraints or {}
    if cons.get("source") == "skipper":
        if cons.get("windMaxKt") is not None:
            facts["wind_max_kt"] = int(round(float(cons["windMaxKt"])))
        if cons.get("hsMaxM") is not None:
            facts["hs_max_m"] = cons["hsMaxM"]
    return facts


def advice_fallback(facts: dict[str, Any]) -> str:
    """Une phrase dont tous les nombres sont déjà dans `facts`."""
    dev = facts.get("max_deviation_nm")
    avoided = facts.get("avoided_points")
    wind = facts.get("wind_max_kt")
    off = facts.get("official_nm")
    rec = facts.get("recomputed_nm")
    if wind is not None and avoided:
        return f"La route s'écarte de {dev} nm pour éviter {avoided} points (vent < {wind} kn)."
    if avoided:
        return f"La route s'écarte de {dev} nm pour éviter {avoided} points."
    return f"La route s'écarte de {dev} nm (distance {off} nm → {rec} nm)."


async def explain_recompute(
    delta: dict[str, Any],
    constraints: dict[str, Any] | None = None,
    *,
    client=None,
    cascade=None,
) -> dict[str, Any]:
    """Nemotron Lightning (tier fast) : une phrase qui reprend les nombres du delta."""
    from story_cascade import cascade_text, filter_numbers, tidy_story  # noqa: PLC0415

    facts = advice_facts(delta, constraints)
    fallback = advice_fallback(facts)
    fn = cascade or cascade_text
    user = (
        "Faits du recalcul (ne pas inventer de chiffre) :\n"
        f"{json.dumps(facts, ensure_ascii=False, default=str)}"
    )
    try:
        text, source = await fn(
            ADVICE_SYSTEM, user, client, tier="fast", fallback=fallback,
            facts=facts, max_tokens=80,
        )
    except Exception as exc:
        log.debug("explication recalcul : %s", exc)
        text, source = fallback, "rules"
    tidy = tidy_story(text or fallback, fallback, max_sentences=1, max_chars=240)
    cleaned, _ = filter_numbers(tidy, facts)
    out = (cleaned or "").strip() or fallback
    if not out:
        out, source = fallback, "rules"
    return {"text": out, "source": source or "rules", "delta": facts}


def _drop_cube(voyage_id: str) -> None:
    import shutil
    from forecast_cube import CACHE_DIR
    shutil.rmtree(CACHE_DIR / voyage_id, ignore_errors=True)
    try:
        from custom_story import drop_cached_moments  # noqa: PLC0415
        drop_cached_moments(voyage_id)
    except Exception as exc:
        log.warning("purge custom-moments %s: %s", voyage_id, exc)


def _check_voyage_size(body: VoyageCreate) -> None:
    if len(body.points) > MAX_VOYAGE_POINTS:
        raise HTTPException(413, f"trop de points ({len(body.points)} > {MAX_VOYAGE_POINTS})")
    if len(body.marks) > MAX_VOYAGE_MARKS:
        raise HTTPException(413, f"trop d'escales ({len(body.marks)} > {MAX_VOYAGE_MARKS})")
    for p in body.points:
        try:
            lat, lon = float(p["lat"]), float(p["lon"])
        except Exception as exc:
            raise HTTPException(400, "point sans lat/lon") from exc
        # Le film déplie les longitudes pour ne pas couper l'antiméridien
        # (Papeete → Wallis → Nouméa dépasse 180°). On borne le tour de
        # globe, pas la valeur brute : refuser > 180 cassait le Suivre.
        if not (-90 <= lat <= 90 and -540 <= lon <= 540) or lat != lat or lon != lon:
            raise HTTPException(400, "point hors limites")


@router.post("/voyage", dependencies=[Depends(_create_limited)])
def create_voyage(body: VoyageCreate, background: BackgroundTasks):
    if not body.points:
        raise HTTPException(400, "points requis")
    _check_voyage_size(body)
    try:
        parse_iso(body.t0)
    except Exception as exc:
        raise HTTPException(400, f"t0 invalide: {exc}") from exc
    # Les brouillons de Simulation ne s'accumulent pas : purge > 7 jours
    # (jamais le voyage officiel) avec leur cube, une fois par création.
    try:
        purge_stale_voyages(STALE_VOYAGE_DAYS, keep={OFFICIAL_VOYAGE_ID}, on_removed=_drop_cube)
    except Exception as exc:  # defensive: never block a visitor for housekeeping
        log.warning("purge voyages: %s", exc)
    if _matches_official_request(body):
        # Route+t0 officiels (empreinte / t0, ou official:true) : stock RF2,
        # jamais _climo_clock dans ce handler.
        voy = _build_official(body, compute_clock=False)
        official_store.kick_worker()
        clock = _official_clock_from_store(voy)
        if clock is None:
            clock = {
                **official_store.preparing_payload("climo", {"t0": OFFICIAL_T0}),
                **_dated_error("horloge officielle en préparation", "preparing"),
            }
        return {**_public_meta(voy), "clock": clock}

    voyage_id = str(uuid.uuid4())
    voy = {
        "voyageId": voyage_id,
        "t0": to_iso(parse_iso(body.t0)),
        "expedition_id": body.expedition_id,
        "routeKind": body.routeKind,
        "routeRev": 0,
        "follow": body.follow,
        "forecast": body.forecast,
        "forecastStatus": "pending" if body.forecast else "unavailable",
        "hindcastStatus": "pending" if body.forecast else "unavailable",
        "forecastModel": None,
        "startAt": body.startAt,
        "points": body.points,
        "marks": body.marks,
        "draft": None,
        "createdAt": to_iso(_now()),
    }
    # Tout autre POST : pas d'_climo_clock ici. Le cube (forecast) ou le
    # worker déjà là calcule hors requête ; le client garde son backoff.
    save_voyage(voy)
    if body.forecast:
        _kick_forecast(voyage_id)
    dated = _dated_error("horloge en préparation", "preparing")
    return JSONResponse(
        status_code=202,
        content={**_public_meta(voy), "clock": dated, **dated},
    )


def _build_official(body: VoyageCreate, *, compute_clock: bool = True) -> dict:
    voy = {
        "voyageId": OFFICIAL_VOYAGE_ID,
        "t0": OFFICIAL_T0,
        "expedition_id": body.expedition_id or "berry-mappemonde-2026",
        "routeKind": "berry",
        "routeRev": 0,
        "follow": True,
        "forecast": False,
        "official": True,
        "forecastStatus": "unavailable",
        "hindcastStatus": "pending",
        "forecastModel": None,
        "startAt": "la-rochelle",
        "points": body.points,
        "marks": body.marks,
        "draft": None,
        "createdAt": to_iso(_now()),
    }
    # Le clock climatologique sur ~1 200 sommets est trop lent pour le boot :
    # GET /voyage/official n'en a pas besoin ; /clock et les kicks le posent.
    if compute_clock:
        voy["clock"] = _climo_clock(voy)
    save_voyage(voy)
    return voy


def _nm_wrap(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine en milles, longitude repliée (même contrat que geo.js)."""
    return haversine(lat1, lon1, lat2, lon1 + delta_lon(lon1, lon2))


def _air_stop_key(name: str) -> str:
    s = (name or "").lower()
    if "cayenne" in s:
        return "cayenne"
    if "halifax" in s:
        return "halifax"
    return ""


def _is_air_leg(from_name: str, to_name: str) -> bool:
    a, b = _air_stop_key(from_name), _air_stop_key(to_name)
    return (a == "cayenne" and b == "halifax") or (a == "halifax" and b == "cayenne")


def official_itinerary_body() -> Optional[VoyageCreate]:
    """Corps ensure_official : itinéraire Berry aplati (pas de réseau)."""
    global _OFFICIAL_BODY_CACHE
    if _OFFICIAL_BODY_CACHE is not None:
        return _OFFICIAL_BODY_CACHE
    if not _ROUTE_GEOJSON.is_file():
        return None
    try:
        fc = json.loads(_ROUTE_GEOJSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("itinéraire Berry embarqué illisible: %s", exc)
        return None

    segments: List[dict] = []
    stops: List[dict] = []
    for feat in (fc.get("features") or []):
        geom = (feat or {}).get("geometry") or {}
        props = (feat or {}).get("properties") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates") or []
        if gtype == "LineString" and len(coords) >= 2:
            segments.append({
                "from": str(props.get("from") or ""),
                "to": str(props.get("to") or ""),
                "coords": coords,
                "nonMaritime": props.get("type") == "overland",
                "air": props.get("type") == "air" or _is_air_leg(
                    str(props.get("from") or ""), str(props.get("to") or ""),
                ),
            })
        elif gtype == "Point" and len(coords) >= 2:
            stops.append({
                "name": str(props.get("name") or ""),
                "lon": float(coords[0]),
                "lat": float(coords[1]),
                "flag": props.get("point_type") == "escale",
            })

    points: List[dict] = []
    cum_nm = 0.0
    film_cum = 0.0

    def _add(lon: float, lat: float, *, jump: bool = False, non_maritime: bool = False, air: bool = False) -> None:
        nonlocal cum_nm, film_cum
        if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))):
            return
        lon_u = float(lon)
        lat_u = float(lat)
        if points:
            prev = points[-1]
            lon_u = _unwrap_lon(prev["lon"], lon_u)
            if abs(prev["lat"] - lat_u) < 1e-9 and abs(prev["lon"] - lon_u) < 1e-6:
                return
            if jump:
                film_cum += _AIR_FILM_NM
            else:
                dist = _nm_wrap(prev["lat"], prev["lon"], lat_u, lon_u)
                if not air:
                    cum_nm += dist
                film_cum += dist
        points.append({
            "lon": lon_u,
            "lat": lat_u,
            "cumNm": cum_nm,
            "filmCum": film_cum,
            "nonMaritime": bool(non_maritime),
            "jump": bool(jump),
            "air": bool(air or jump),
        })

    for seg in segments:
        coords = seg["coords"]
        air = bool(seg["air"])
        start = 0
        if points:
            lon0, lat0 = coords[0][0], coords[0][1]
            prev = points[-1]
            if (
                isinstance(lat0, (int, float))
                and isinstance(lon0, (int, float))
                and _nm_wrap(prev["lat"], prev["lon"], float(lat0), float(lon0)) >= _AIR_JUMP_NM
            ):
                _add(float(lon0), float(lat0), jump=True, non_maritime=seg["nonMaritime"], air=True)
                start = 1
        for i in range(start, len(coords)):
            pair = coords[i]
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            _add(float(pair[0]), float(pair[1]), non_maritime=seg["nonMaritime"], air=air)

    if not points:
        return None

    marks: List[dict] = []
    search = 0
    for stop in stops:
        if not stop.get("flag") or not stop.get("name"):
            continue
        best = search
        best_d = float("inf")
        for i in range(search, len(points)):
            d = _nm_wrap(stop["lat"], stop["lon"], points[i]["lat"], points[i]["lon"])
            if d < best_d:
                best_d = d
                best = i
        pt = points[best]
        marks.append({
            "name": stop["name"],
            "lat": stop["lat"],
            "lon": stop["lon"],
            "nm": pt["cumNm"],
            "filmNm": pt.get("filmCum", pt["cumNm"]),
            "index": best,
            "flag": True,
        })
        search = best

    body = VoyageCreate(
        t0=OFFICIAL_T0,
        expedition_id="berry-mappemonde-2026",
        routeKind="berry",
        follow=True,
        forecast=False,
        startAt="la-rochelle",
        official=True,
        points=points,
        marks=marks,
    )
    _OFFICIAL_BODY_CACHE = body
    return body


def _auto_seed_official_enabled() -> bool:
    """Pytest : pas de semis au boot (fixtures PUT à 3 points). force = tests ciblés."""
    raw = (os.getenv("NAVIGUIDE_SEED_OFFICIAL") or "1").strip().lower()
    if raw in ("0", "false", "no"):
        return False
    if raw == "force":
        return True
    if os.getenv("PYTEST_CURRENT_TEST"):
        return False
    return True


def seed_official_voyage() -> Optional[dict]:
    """Crée le voyage officiel s'il manque, sans client ni clé. Sans clock (boot)."""
    existing = load_voyage(OFFICIAL_VOYAGE_ID)
    if existing and existing.get("points"):
        return existing
    body = official_itinerary_body()
    if body is None or not body.points:
        return None
    log.info("voyage officiel semé côté serveur (%s points)", len(body.points))
    return _build_official(body, compute_clock=False)


def _wait_official_kick(provider: str, timeout: float = 900.0) -> None:
    """Attend la fin d'un kick pipeline. Appelé depuis le fil de warm, pas HTTP."""
    deadline = time.monotonic() + float(timeout)
    pipe = get_pipeline()
    while time.monotonic() < deadline:
        if not pipe.provider_busy(provider):
            return
        time.sleep(0.2)


def kick_official_warmups(*, force: bool = False) -> None:
    """Un préchauffage après l'autre — jamais les cinq en parallèle."""
    _kick_official_grib()
    _wait_official_kick("official-grib")
    _kick_official_hindcast(force=force)
    _wait_official_kick("official-hindcast")
    _kick_official_eta(force=force)
    _wait_official_kick("official-eta")
    _kick_official_moments(force=force)
    _wait_official_kick("official-moments")
    _kick_official_film_story(force=force)
    _wait_official_kick("official-film-story")


def startup_official_voyage() -> Optional[dict]:
    """Semis + travail de fond du stock : le boot uvicorn ne bloque pas."""
    voy = seed_official_voyage()
    official_store.start_worker()
    return voy


def _resolve_grib_around(
    voy: Optional[dict],
    when: datetime,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> Optional[dict]:
    if lat is not None and lon is not None:
        return {"lat": lat, "lon": lon}
    if voy:
        around = _grib_around_from_live(voy, when)
        if around and around.get("lat") is not None:
            return around
    latest = load_latest(OFFICIAL_VOYAGE_ID)
    around = (latest or {}).get("around")
    if around and around.get("lat") is not None:
        return around
    return None


def _kick_official_grib(
    around: Optional[dict] = None,
    when: Optional[datetime] = None,
    *,
    force: Optional[bool] = None,
) -> bool:
    """Démarre au plus un rafraîchissement GRIB pour cette cellule/cycle.

    Un GET ne force jamais : on calcule seulement si la donnée manque ou est
    périmée, et jamais pendant un calcul en cours. Le travail tourne dans un
    processus enfant.
    """
    target_when = when or _now()
    if around is None:
        voy = load_voyage(OFFICIAL_VOYAGE_ID)
        around = _resolve_grib_around(voy, target_when)
    if not around or around.get("lat") is None or around.get("lon") is None:
        return False
    forced = bool(force)
    if not forced:
        latest = load_latest(OFFICIAL_VOYAGE_ID, utc_day(target_when))
        if latest and latest.get("status") == "ready" and not is_stale(latest, target_when):
            return False
    # Processus enfant tué à l'échéance du fournisseur (weather_jobs).
    job = ProcessJob(
        "weather_jobs:refresh_official_grib",
        dict(around),
        to_iso(target_when),
        forced,
    )
    return get_async_weather_queue().submit(
        "grib-wind",
        float(around["lat"]),
        float(around["lon"]),
        job,
        when=target_when,
        force=forced,
    )


def _official_grib_refreshing() -> bool:
    return get_async_weather_queue().provider_busy("grib-wind")


def _grib_wind_layer(record: Optional[dict], around: Optional[dict], when: datetime, *, refreshing: bool) -> str:
    lat = (around or {}).get("lat")
    lon = (around or {}).get("lon")
    cached = None
    if lat is not None and lon is not None:
        cached = get_async_weather_queue().cached_status("grib-wind", float(lat), float(lon), when)
    # Un état final l'emporte sur un « en cours » ; un pending trop vieux est
    # déjà rendu unavailable par la file (PENDING_MAX_AGE_S).
    if record and record.get("status") == "ready":
        return "ready"
    if cached == "unavailable":
        return "unavailable"
    if cached == "ready":
        return "ready"
    if cached == "pending" or refreshing:
        return "pending"
    return "unavailable"


def _regime_portions(clock: dict) -> list:
    portions = []
    current = None
    for v in clock.get("vertices") or []:
        if v.get("vehicle") in ("plane", "side"):
            continue
        regime = v.get("regime") or v.get("kind") or "climatology"
        if current is None or current["regime"] != regime:
            if current:
                portions.append(current)
            current = {
                "regime": regime,
                "fromNm": v.get("sailNm"),
                "toNm": v.get("sailNm"),
                "fromIso": v.get("iso"),
                "toIso": v.get("iso"),
                "sources": list(v.get("sources") or []),
                "spread": v.get("spread"),
            }
        else:
            current["toNm"] = v.get("sailNm")
            current["toIso"] = v.get("iso")
            for src in v.get("sources") or []:
                if src not in current["sources"]:
                    current["sources"].append(src)
            if v.get("spread") is not None:
                prev = current.get("spread")
                current["spread"] = v["spread"] if prev is None else max(prev, v["spread"])
    if current:
        portions.append(current)
    return portions


def _kick_official_moments(*, force: bool = False) -> bool:
    """Remplit le journal des moments en fond — jamais bloquant."""
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    if voy is None:
        return False

    def _load():
        try:
            from moment_journal import warm_moments  # noqa: PLC0415
            warm_moments(OFFICIAL_VOYAGE_ID)
        except Exception as exc:
            log.warning("journal des moments: %s", exc)
        _kick_official_film_story(force=True)
        return {}

    return get_pipeline().kick(
        "official-moments",
        0.0,
        0.0,
        _load,
        force=force,
    )


def _kick_official_film_story(*, force: bool = False) -> bool:
    """Préchauffe le récit du film après le journal — jamais bloquant."""
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    if voy is None:
        return False

    def _load():
        try:
            import asyncio  # noqa: PLC0415
            from film_script import warm_film_story  # noqa: PLC0415

            try:
                asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(warm_film_story(OFFICIAL_VOYAGE_ID))
            else:
                asyncio.create_task(warm_film_story(OFFICIAL_VOYAGE_ID))
        except Exception as exc:
            log.warning("préchauffage récit film: %s", exc)
        return {}

    return get_pipeline().kick(
        "official-film-story",
        0.0,
        0.0,
        _load,
        force=force,
    )


def _kick_official_hindcast(*, force: bool = False) -> bool:
    """L'ERA5 officiel appartient au remplisseur (trajet réel figé,
    cellules demandées par l'intégration — jamais par les dates de l'horloge
    climatologique du jour). Ici on ne fait que le réveiller."""
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    if voy is None:
        return False

    def _load():
        official_store.kick_worker()
        return {}

    return get_pipeline().kick(
        "official-hindcast",
        0.0,
        0.0,
        _load,
        force=force,
    )


def _kick_official_eta(*, force: bool = False, stop: Optional[str] = None) -> bool:
    """Préchauffe l'ensemble ETA du voyage officiel, sans bloquer l'appelant.

    Un premier vide n'est pas terminal. RE5 : on ne martèle
    plus à chaque GET — tant que ``nextRetry`` n'est pas échu, pas de relance.
    """
    raw = (os.getenv("NAVIGUIDE_ETA_PREHEAT") or "1").strip().lower()
    if raw in ("0", "false", "no"):
        return False
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    if voy is None:
        return False

    if not force:
        from ensemble_eta import eta_retry_due, next_official_stop, peek_official_eta  # noqa: PLC0415
        target = (stop or "").strip() or next_official_stop(voy, _now())
        if target:
            peeked = peek_official_eta(voy, target, _now())
            members = peeked.get("members") if isinstance(peeked, dict) else 0
            try:
                n = int(members or 0)
            except (TypeError, ValueError):
                n = 0
            if n <= 0 and eta_retry_due(peeked, _now()):
                force = True

    def _load():
        try:
            from ensemble_eta import preheat_official_eta  # noqa: PLC0415
            current = load_voyage(OFFICIAL_VOYAGE_ID) or voy
            preheat_official_eta(
                current,
                _now(),
                polar_raw=_polar_raw((current or {}).get("expedition_id") or ""),
                stop=stop,
            )
        except Exception as exc:
            log.warning("préchauffage ETA officiel: %s", exc)
        return {}

    return get_pipeline().kick(
        "official-eta",
        0.0,
        0.0,
        _load,
        when=_now(),
        force=force,
    )


def _maybe_daily_hindcast(voy: dict) -> None:
    last = voy.get("hindcastRefreshedAt")
    if last:
        try:
            age_h = (_now() - parse_iso(last)).total_seconds() / 3600.0
        except Exception:
            age_h = 99.0
        if age_h < 20.0 and voy.get("hindcastStatus") == "ready":
            _kick_official_eta(force=False)
            _kick_official_moments(force=False)
            return
    if om_quota_blocked() and voy.get("hindcastStatus") in ("empty", "partial"):
        _kick_official_eta(force=False)
        _kick_official_moments(force=False)
        return
    _kick_official_hindcast(force=False)
    _kick_official_eta(force=True)
    _kick_official_moments(force=False)


def _kick_forecast(voyage_id: str, *, force: bool = True) -> bool:
    voy = load_voyage(voyage_id)
    pts = (voy or {}).get("points") or []
    lat = float(pts[0]["lat"]) if pts else 0.0
    lon = float(pts[0]["lon"]) if pts else 0.0

    def _load():
        _fill_forecast(voyage_id)
        return {}

    return get_pipeline().kick(
        f"forecast-cube:{voyage_id}",
        lat,
        lon,
        _load,
        force=force,
    )


@router.put("/voyage/official", dependencies=[Depends(_official_read_limited)])
def ensure_official(body: VoyageCreate, background: BackgroundTasks, request: Request):
    """Chaque visiteur envoie ce PUT au chargement (auto-réparation).

    Sécurité P0 : un visiteur anonyme ne peut que *créer* le voyage officiel
    s'il manque (disque neuf) — jamais modifier route, escales ou expédition
    d'un voyage existant. Seul l'admin (X-Naviguide-Admin) met à jour.
    """
    if not body.points:
        raise HTTPException(400, "points requis")
    _check_voyage_size(body)
    existing = load_voyage(OFFICIAL_VOYAGE_ID)
    if existing and existing.get("points"):
        changed = False
        if is_admin(request):
            if (
                len(body.points) > len(existing["points"])
                and int(existing.get("routeRev") or 0) == 0
            ):
                existing["points"] = body.points
                existing["marks"] = body.marks
                existing["t0"] = OFFICIAL_T0
                existing["official"] = True
                changed = True
            if body.expedition_id and body.expedition_id != existing.get("expedition_id"):
                existing["expedition_id"] = body.expedition_id
                changed = True
        if changed:
            save_voyage(existing)
            log.info("voyage officiel mis à jour par l'admin (%s points)", len(existing["points"]))
        # Admin : passage complet (kick_worker). Visiteur : réparation bornée —
        # relance un remplisseur mort et ne le réveille que si le climo du jour manque.
        background.add_task(official_store.kick_worker if is_admin(request) else official_store.repair_worker)
        clock = official_store.stored_clock() or existing.get("clock")
        meta = _public_meta(existing)
        if clock:
            meta["clock"] = clock
        return meta
    log.warning("voyage officiel absent : créé depuis un client (%s points)", len(body.points))
    # Route officielle (~1 200 pts) : jamais d'horloge sur la requête.
    # Fixtures de test (quelques points) : horloge locale, aucun fournisseur.
    voy = _build_official(body, compute_clock=len(body.points) < 80)
    background.add_task(official_store.kick_worker)
    clock = official_store.stored_clock() or voy.get("clock")
    meta = _public_meta(voy)
    if clock:
        meta["clock"] = clock
    return meta


@router.get("/voyage/official")
def get_official():
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    if voy is None or not voy.get("points"):
        voy = seed_official_voyage()
    if voy is None:
        raise HTTPException(404, "voyage officiel absent")
    return {
        **_public_meta(voy),
        "points": voy.get("points"),
        "marks": voy.get("marks"),
        "params": official_clock_params(),
    }


@router.get("/voyage/official/clock")
def get_official_clock():
    """Horloge officielle : lue du stock RF2 — jamais un calcul sur la requête."""
    try:
        raw = official_store.serve_clock_bytes()
        if raw:
            # Climo du jour sans realUntil → nudge le remplisseur,
            # sans recalculer ici. L'horloge déjà rangée est servie telle quelle.
            official_store.nudge_climo_if_missing_real_until()
            return Response(content=raw, media_type="application/json")
        voy = load_voyage(OFFICIAL_VOYAGE_ID)
        clock = _official_clock_from_store(voy)
        if clock:
            return clock
    except Exception as exc:
        log.exception("GET /voyage/official/clock")
        official_store.kick_worker()
        return official_store.preparing_payload("climo", {
            "t0": OFFICIAL_T0,
            **_dated_error(f"horloge officielle indisponible: {exc}", "preparing"),
        })
    official_store.kick_worker()
    return official_store.preparing_payload("climo", {
        "t0": OFFICIAL_T0,
        **_dated_error("horloge officielle en préparation", "preparing"),
    })


@router.get("/voyage/official/regimes")
def get_official_regimes():
    """Portions de route par régime — snapshot du stock."""
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    climo = official_store.serve_climo()
    clock = (climo or {}).get("clock") or official_store.stored_clock() or (voy or {}).get("clock")
    if not clock:
        official_store.kick_worker()
        return official_store.preparing_payload("climo", {
            "voyageId": OFFICIAL_VOYAGE_ID,
            "kind": "climatology",
            "portions": [],
        })
    portions = (climo or {}).get("regimes")
    if portions is None:
        portions = _regime_portions(clock)
    return {
        "voyageId": OFFICIAL_VOYAGE_ID,
        "kind": clock.get("kind") or "climatology",
        "hindcastStatus": (voy or {}).get("hindcastStatus"),
        "hindcastCoverage": (voy or {}).get("hindcastCoverage"),
        "hindcastReason": (voy or {}).get("hindcastReason"),
        "portions": portions,
        "status": "ready",
    }


class JournalNoteIn(BaseModel):
    text: str
    author: Optional[str] = None
    lang: Optional[str] = "fr"
    t: Optional[str] = None


def _stored_moments_in_english(rows: list[dict]) -> list[dict]:
    """Only reuse cached rows when their language is explicitly identified.

    The official frozen journal is French and has no localized companion
    fields. Guessing from place names or translating prose heuristically would
    leak French into the English view, so unknown-language rows are omitted.
    """
    return [
        row for row in rows or []
        if isinstance(row, dict)
        and str(row.get("lang") or row.get("language") or "").lower().startswith("en")
    ]


@router.get("/voyage/official/moments")
def get_official_moments(
    until: str | None = Query(None, description="ISO : ne garder que les lignes t ≤ until"),
    lang: str = Query("fr"),
):
    """Journal des moments — lu du stock RF2, jamais un warm sur la requête."""
    try:
        out = official_store.serve_moments(until=until)
        if lang.lower().startswith("en") and out.get("status") != official_store.PREPARING:
            voy = load_voyage(OFFICIAL_VOYAGE_ID)
            if voy is not None:
                from moment_journal import _with_clock, rows_from_voyage  # noqa: PLC0415

                rows = rows_from_voyage(OFFICIAL_VOYAGE_ID, _with_clock(voy), lang="en")
                # The frozen/offline voyage may not contain the pearl history
                # needed to rebuild the localized view. Keep the stored journal
                # only when rows identify themselves as English; the official
                # frozen rows are French and must not leak into this response.
                if not rows:
                    rows = _stored_moments_in_english(out.get("moments") or [])
                if until:
                    from moment_journal import _iso_le  # noqa: PLC0415

                    rows = [row for row in rows if _iso_le(row.get("t"), until)]
                out = {**out, "count": len(rows), "moments": rows}
    except Exception as exc:
        log.exception("GET /voyage/official/moments")
        official_store.kick_worker()
        return official_store.preparing_payload("moments", {
            "voyageId": OFFICIAL_VOYAGE_ID, "until": until, "count": 0, "moments": [],
            **_dated_error(f"journal indisponible: {exc}", "preparing"),
        })
    if out.get("status") == official_store.PREPARING:
        official_store.kick_worker()
    return out


@router.get("/voyage/official/journal")
def get_official_journal(
    limit: int = Query(50, ge=1, le=500),
    kinds: str | None = Query(None, description="filtre `latest` : kinds séparés par des virgules (zee,amp,poe,wx,…)"),
):
    """La mémoire du voyage officiel — snapshot du stock RF2, sans tick HTTP."""
    wanted = tuple(k.strip() for k in kinds.split(",") if k.strip() in journal.KINDS) if kinds else None
    try:
        out = official_store.serve_journal(limit, wanted)
        if out.get("status") != official_store.PREPARING:
            return out
        # Fichiers déjà écrits hors requête (tick du travail de fond, notes) :
        # on les sert tels quels, on ne tick pas.
        legacy = journal.summary(limit)
        if (legacy.get("count") or 0) > 0:
            if wanted:
                legacy["latest"] = journal.latest(limit, kinds=wanted)
            return {"voyageId": OFFICIAL_VOYAGE_ID, "status": "ready", **legacy}
        official_store.kick_worker()
        return out
    except Exception as exc:
        log.exception("GET /voyage/official/journal")
        official_store.kick_worker()
        return official_store.preparing_payload("moments", {
            "voyageId": OFFICIAL_VOYAGE_ID, "latest": [], "count": 0, "days": [],
            **_dated_error(f"journal indisponible: {exc}", "preparing"),
        })


@router.get("/voyage/official/eta")
def get_official_eta(stop: str = Query(..., min_length=1)):
    """Fourchette p10–p90 — lue du stock RF2, jamais un fetch sur la requête."""
    try:
        out = official_store.serve_eta(stop)
    except Exception as exc:
        log.exception("GET /voyage/official/eta")
        official_store.kick_worker()
        from ensemble_eta import empty_eta  # noqa: PLC0415
        empty = empty_eta(_now(), reason=f"fourchette indisponible: {exc}")
        empty.update(_dated_error(f"fourchette indisponible: {exc}", "preparing"))
        return empty
    if out.get("status") == official_store.PREPARING:
        official_store.kick_worker()
    return out


@router.get("/voyage/official/plan-review")
def get_official_plan_review():
    """Revue de plan — snapshot du stock RF2, sans atlas ni LLM sur la requête."""
    try:
        out = official_store.serve_plan_review()
    except Exception as exc:
        log.exception("GET /voyage/official/plan-review")
        official_store.kick_worker()
        return official_store.preparing_payload("plan_review", {
            "legs": [],
            **_dated_error(f"revue indisponible: {exc}", "preparing"),
        })
    if out.get("status") == official_store.PREPARING:
        official_store.kick_worker()
    return out


def _rewrite_plan_advice(payload: dict) -> dict:
    """Réécriture LLM de la phrase du meilleur, sous filter_numbers (repli gabarit)."""
    from story_cascade import cascade_text, filter_numbers, tidy_story  # noqa: PLC0415

    out = payload
    cand = out.get("best") if isinstance(out, dict) else None
    if not isinstance(cand, dict):
        return out
    facts = cand.get("facts")
    fallback = str(cand.get("sentence") or "").strip()
    user = (
        "Réécris cette phrase de conseil de dates en UNE phrase. "
        "Tu ne produis aucun chiffre qui n'est pas déjà dans les faits.\n"
        f"Faits : {json.dumps(facts, ensure_ascii=False, default=str)}\n"
        f"Gabarit : {fallback}"
    )
    try:
        text, source = _run_async(cascade_text(
            ADVICE_SYSTEM, user, None, tier="fast", fallback=fallback,
            facts=facts, max_tokens=80,
        ))
    except Exception as exc:
        log.debug("conseil dates : %s", exc)
        text, source = fallback, "rules"
    tidy = tidy_story(text or fallback, fallback, max_sentences=1, max_chars=280)
    cleaned, _ = filter_numbers(tidy, facts)
    cand["sentence"] = (cleaned or "").strip() or fallback
    cand["sentenceSource"] = source or "rules"
    cand["sentenceLang"] = "fr"
    return out


def _localize_plan_advice(payload: dict, lang: str) -> dict:
    """Texte rédigé en anglais si l'UI est EN ; copie, jamais le cache du job."""
    out = copy.deepcopy(payload) if isinstance(payload, dict) else payload
    cand = out.get("best") if isinstance(out, dict) else None
    if not isinstance(cand, dict):
        return out
    lg = (lang or "fr")[:2].lower()
    text = str(cand.get("sentence") or "").strip()
    if lg == "en" and text:
        try:
            from story_cache import translate_through_cache  # noqa: PLC0415
            translated, source = _run_async(translate_through_cache(text, "en"))
            if translated:
                cand["sentence"] = translated
                cand["sentenceLang"] = "en"
                cand["sentenceSource"] = source or cand.get("sentenceSource") or "rules"
                out["best"] = cand
                return out
        except Exception as exc:
            log.debug("traduction conseil : %s", exc)
    cand.setdefault("sentenceLang", "fr")
    out["best"] = cand
    return out


@router.get("/voyage/official/advice")
def get_official_advice(
    leg: int = Query(..., ge=0, le=400),
    lang: str = Query("fr"),
):
    """Compromis par décalage de date. pending|done|unavailable — jamais 400 d'indice."""
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    if voy is None:
        raise HTTPException(404, "voyage officiel absent")
    from plan_advisor import request_advice  # noqa: PLC0415
    try:
        out = request_advice(voy, int(leg), now=_now(), rewrite=_rewrite_plan_advice)
    except ValueError:
        from plan_advisor import advice_unavailable  # noqa: PLC0415
        return advice_unavailable(int(leg), "unknown_leg")
    if out.get("status") == "done":
        return _localize_plan_advice(out, lang)
    return out


@router.get("/voyage/official/journal/{day}")
def get_official_journal_day(day: str):
    try:
        stored = official_store.serve_journal_day(day)
        if stored is not None:
            return {"voyageId": OFFICIAL_VOYAGE_ID, "day": day, "entries": stored, "status": "ready"}
        entries = journal.read_day(day)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not entries:
        raise HTTPException(404, "aucune entrée ce jour")
    return {"voyageId": OFFICIAL_VOYAGE_ID, "day": day, "entries": entries}


@router.post("/voyage/official/journal/note", dependencies=[Depends(require_admin)])
def post_official_journal_note(body: JournalNoteIn):
    """Mot du skipper / de l'équipe — la seule écriture humaine du journal."""
    when = _now()
    if body.t:
        try:
            when = parse_iso(body.t)
        except Exception as exc:
            raise HTTPException(400, f"t invalide: {exc}") from exc
    try:
        entry = journal.add_note(body.text, when, author=body.author or "skipper", lang=body.lang or "fr")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    official_store.append_note_to_store(entry)
    return entry


def _grib_around_from_live(voy: Optional[dict], when: datetime) -> Optional[dict]:
    """Couloir horloge : ici → position à l’ETA du prochain téléchargement."""
    if not voy:
        return None
    clock = official_store.stored_clock() or (voy or {}).get("clock")
    if not clock:
        return None
    around = track_from_clock(clock, when)
    if around:
        return around
    sample = sample_clock_at_time(clock, when)
    if not sample:
        return None
    return {"lat": sample.get("lat"), "lon": sample.get("lon")}


def _saildocs_query_from_around(around: dict) -> str:
    return saildocs_query(
        float(around["lat"]),
        float(around["lon"]),
        dest=around.get("dest"),
        waypoints=around.get("waypoints"),
    )


def _saildocs_queries_from_around(around: dict) -> list:
    return saildocs_queries(
        float(around["lat"]),
        float(around["lon"]),
        dest=around.get("dest"),
        waypoints=around.get("waypoints"),
    )


def _latest_official_grib(around: Optional[dict], when) -> Optional[dict]:
    record = load_latest(OFFICIAL_VOYAGE_ID, utc_day(when))
    if around and is_stale(record, when):
        _kick_official_grib(around, when)
    return record


def _pending_grib(record: Optional[dict], around: Optional[dict], when: datetime, *, refreshing: bool) -> dict:
    body = public_grib(record, OFFICIAL_VOYAGE_ID, around, when)
    if not record or record.get("status") != "ready":
        body["status"] = "pending" if refreshing else "absent"
        body["warning"] = None if refreshing else body.get("warning")
        if refreshing:
            body["products"] = [
                {**product, "status": "pending"}
                for product in (body.get("products") or [])
            ]
    body["refreshing"] = refreshing
    body["layers"] = {
        "gribWind": {
            "provider": "grib-wind",
            "status": _grib_wind_layer(record, around, when, refreshing=refreshing),
        }
    }
    return body


@router.get("/voyage/official/at")
def official_at(t: Optional[str] = Query(None)):
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    if voy is None:
        raise HTTPException(404, "voyage officiel absent")
    clock = _official_clock_from_store(voy)
    if not clock:
        official_store.kick_worker()
        return official_store.preparing_payload("climo", _dated_error("horloge officielle en préparation", "preparing"))
    when = parse_iso(t) if t else _now()
    sample = sample_clock_at_time(clock, when)
    if sample is None:
        raise HTTPException(404, "horloge vide")
    sample["voyageId"] = OFFICIAL_VOYAGE_ID
    sample["t"] = to_iso(when)
    around = _grib_around_from_live(voy, when)
    grib = load_latest(OFFICIAL_VOYAGE_ID, utc_day(when))
    wind = wind_at_daily(grib, float(sample.get("lat") or 0), float(sample.get("lon") or 0), when)
    sample["regime"] = sample.get("regime") or sample.get("kind") or "climatology"
    sample["sources"] = list(sample.get("sources") or [])
    if wind:
        sample["kind"] = "forecast"
        sample["model"] = wind.get("model")
        sample["waveModel"] = wind.get("waveModel")
        sample["currentModel"] = wind.get("currentModel")
        sample["windKnots"] = wind.get("windKnots")
        sample["dirFromDeg"] = wind.get("dirFromDeg")
        sample["pressHpa"] = wind.get("pressHpa")
        sample["rainMm"] = wind.get("rainMm")
        sample["hs"] = wind.get("hs")
        sample["gribStatus"] = "ready"
        sample["gribWarning"] = None
    else:
        sample["kind"] = "absent"
        sample["model"] = None
        sample["leadHours"] = None
        sample["windKnots"] = None
        sample["dirFromDeg"] = None
        sample["gribStatus"] = "absent"
        sample["gribWarning"] = GRIB_MISSING
    return sample


@router.get("/voyage/official/grib")
def get_official_grib(
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
    t: Optional[str] = Query(None),
):
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    when = parse_iso(t) if t else _now()
    around = _resolve_grib_around(voy, when, lat, lon)
    record = load_latest(OFFICIAL_VOYAGE_ID, utc_day(when))
    if record is None and around:
        record = scan_inbox(OFFICIAL_VOYAGE_ID, utc_day(when), around)
    requested = bool(around and is_stale(record, when) and _kick_official_grib(around, when))
    refreshing = requested or _official_grib_refreshing()
    body = _pending_grib(record, around, when, refreshing=refreshing)
    if lat is not None and lon is not None and record:
        body["wind"] = wind_at_daily(record, lat, lon, when)
    return body


@router.post("/voyage/official/grib", dependencies=[Depends(require_admin)])
def post_official_grib(body: DailyGribIn):
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    around = body.around
    if around is None and voy:
        around = _grib_around_from_live(voy, _now())
    try:
        record = ingest_daily(OFFICIAL_VOYAGE_ID, body.model_dump(), around=around)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return public_grib(record, OFFICIAL_VOYAGE_ID, around or body.around, _now())


@router.post("/voyage/official/grib/refresh", dependencies=[Depends(require_admin)])
def refresh_official_grib(
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
):
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    when = _now()
    around = _resolve_grib_around(voy, when, lat, lon)
    record = load_latest(OFFICIAL_VOYAGE_ID, utc_day(when))
    if record is None and around:
        record = scan_inbox(OFFICIAL_VOYAGE_ID, utc_day(), around)
    requested = bool(around and _kick_official_grib(around, when, force=True))
    refreshing = requested or _official_grib_refreshing()
    return _pending_grib(record, around, when, refreshing=refreshing)


@router.post("/voyage/official/grib/scan", dependencies=[Depends(require_admin)])
def scan_official_grib():
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    around = _grib_around_from_live(voy, _now()) if voy else None
    record = scan_inbox(OFFICIAL_VOYAGE_ID, utc_day(), around)
    if record is None:
        return absent_payload(OFFICIAL_VOYAGE_ID, utc_day(), around)
    return public_grib(record, OFFICIAL_VOYAGE_ID, around, _now())


@router.get("/voyage/official/saildocs-query")
def official_saildocs_query(
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
):
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    around = _grib_around_from_live(voy, _now()) if voy else None
    if around is None and lat is not None and lon is not None:
        around = {"lat": lat, "lon": lon}
    if not around:
        raise HTTPException(400, "position bateau inconnue")
    queries = _saildocs_queries_from_around(around)
    return {
        "query": queries[0]["query"],
        "queries": queries,
        "around": around,
        "radiusNm": DAILY_RADIUS_NM,
        "model": "GFS",
        "models": [p["model"] for p in GRIB_PRODUCTS],
        "nextDownloadAt": around.get("nextDownloadAt") or to_iso(dest_eta_at_next_download()),
        "horizonHours": around.get("horizonHours"),
        "cycle": around.get("cycle") or to_iso(last_ready_cycle()),
    }


@router.get("/voyage/{voyage_id}")
def get_voyage(voyage_id: str):
    voy = load_voyage(voyage_id)
    if voy is None:
        raise HTTPException(404, "voyage inconnu")
    return {
        **_public_meta(voy),
        "points": voy.get("points"),
        "marks": voy.get("marks"),
    }


@router.get("/voyage/{voyage_id}/moments")
def get_voyage_moments(voyage_id: str):
    """Moments de MA route : calcul à la demande, cache kv, jamais le stock officiel."""
    if _is_official(voyage_id):
        return get_official_moments()
    voy = load_voyage(voyage_id)
    if voy is None:
        raise HTTPException(404, "voyage inconnu")
    try:
        from custom_story import moments_for_voyage  # noqa: PLC0415
        return moments_for_voyage(voy)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("GET /voyage/%s/moments", voyage_id)
        from custom_story import preparing_payload  # noqa: PLC0415
        return preparing_payload(voy, reason=str(exc))


@router.get("/voyage/{voyage_id}/film")
def get_voyage_film(
    voyage_id: str,
    lang: str = Query("fr"),
    seconds: int = Query(150, ge=0, le=300),
    style: str = Query("raw"),
):
    """Film de MA route : même forme que l'officiel, brut seulement, jamais de LLM."""
    # Le chemin /voyage/official/film est aussi sur main.py ; ce paramètre le
    # capte si la route générique est enregistrée avant — on délègue, on ne
    # recalcule pas.
    if _is_official(voyage_id) or voyage_id == "official":
        return official_store.serve_film(lang=lang, seconds=seconds, style=style)
    voy = load_voyage(voyage_id)
    if voy is None:
        raise HTTPException(404, "voyage inconnu")
    try:
        from custom_story import film_for_voyage, moments_for_voyage  # noqa: PLC0415
        mom = moments_for_voyage(voy)
        return film_for_voyage(voy, mom, lang=lang, seconds=seconds, style=style)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("GET /voyage/%s/film", voyage_id)
        from custom_story import preparing_film_payload  # noqa: PLC0415
        return preparing_film_payload(voy, lang=lang, seconds=seconds, style=style, reason=str(exc))


@router.get("/voyage/{voyage_id}/clock")
def get_clock(voyage_id: str):
    voy = load_voyage(voyage_id)
    if voy is None:
        raise HTTPException(404, "voyage inconnu")
    if _is_official(voyage_id):
        clock = _official_clock_from_store(voy)
        if not _clock_has_vertices(clock):
            official_store.kick_worker()
            return official_store.preparing_payload("climo", {
                "t0": OFFICIAL_T0,
                **_dated_error("horloge officielle en préparation", "preparing"),
            })
        return clock
    clock = voy.get("clock")
    if _clock_has_vertices(clock):
        return clock
    # Voyage non officiel sans sommets : 200 daté, jamais 503.
    # Aucune horloge inventée dans ce handler.
    return _preparing_clock_body(voy, "horloge en préparation")


@router.get("/voyage/{voyage_id}/at")
def get_at(voyage_id: str, t: Optional[str] = Query(None)):
    voy = load_voyage(voyage_id)
    if voy is None:
        raise HTTPException(404, "voyage inconnu")
    if _is_official(voyage_id):
        clock = _official_clock_from_store(voy)
        if not _clock_has_vertices(clock):
            official_store.kick_worker()
            return {"voyageId": voyage_id, "t": t, **_dated_error("horloge officielle en préparation", "preparing")}
    else:
        clock = voy.get("clock")
        if not _clock_has_vertices(clock):
            # Même contrat que l'officiel preparing : 200 daté, jamais 503.
            return {"voyageId": voyage_id, "t": t, **_dated_error("horloge en préparation", "preparing")}
    if not _clock_has_vertices(clock):
        return {"voyageId": voyage_id, "t": t, **_dated_error("horloge officielle en préparation", "preparing")}
    when = parse_iso(t) if t else _now()
    sample = sample_clock_at_time(clock, when)
    if sample is None:
        raise HTTPException(404, "horloge vide")
    t0 = parse_iso(voy["t0"])
    hours_from_now = (when - _now()).total_seconds() / 3600.0
    if hours_from_now > FORECAST_BLEND_END_HOURS and sample.get("kind") == "forecast":
        sample["kind"] = "climatology"
        sample["regime"] = "climatology"
        sample["leadHours"] = None
        sample["model"] = None
    sample["regime"] = sample.get("regime") or sample.get("kind") or "climatology"
    sample["sources"] = list(sample.get("sources") or [])
    sample["voyageId"] = voyage_id
    sample["forecastStatus"] = voy.get("forecastStatus")
    sample["forecastModel"] = voy.get("forecastModel")
    sample["t"] = to_iso(when)
    if sample.get("kind") == "forecast":
        # Lead time = heures depuis maintenant (origine du cube), plus depuis t0.
        sample["leadHours"] = round(max(0.0, hours_from_now), 1)
        if not sample.get("model"):
            sample["model"] = voy.get("forecastModel")
    return sample


@router.post("/voyage/{voyage_id}/refresh-forecast", dependencies=[Depends(_compute_limited)])
def refresh_forecast(voyage_id: str, background: BackgroundTasks, request: Request):
    if _is_official(voyage_id) and not is_admin(request):
        raise HTTPException(403, "le voyage officiel n'a pas de cube de prévision public")
    voy = load_voyage(voyage_id)
    if voy is None:
        raise HTTPException(404, "voyage inconnu")
    update_voyage(voyage_id, forecastStatus="pending")
    _kick_forecast(voyage_id)
    return _public_meta(load_voyage(voyage_id) or voy)


def _maybe_auto_refresh(voy: dict) -> None:
    refreshed = voy.get("forecastRefreshedAt")
    if not refreshed or voy.get("forecastStatus") != "ready":
        return
    age = (_now() - parse_iso(refreshed)).total_seconds() / 3600.0
    if age >= CACHE_TTL_H and voy.get("follow"):
        _kick_forecast(voy["voyageId"])


@router.post("/voyage/{voyage_id}/recompute", dependencies=[Depends(_compute_limited)])
def recompute(voyage_id: str, body: Optional[RecomputeBody] = None):
    body = body or RecomputeBody()
    if _is_official(voyage_id):
        raise HTTPException(403, "recalcul interdit sur le voyage officiel")
    voy = load_voyage(voyage_id)
    if voy is None:
        raise HTTPException(404, "voyage inconnu")
    _maybe_auto_refresh(voy)
    clock = voy.get("clock")
    if not isinstance(clock, dict) or not clock.get("vertices"):
        try:
            clock = _climo_clock(voy)
        except Exception as exc:
            log.exception("recompute: horloge climato échouée")
            raise HTTPException(503, _dated_error(f"horloge climato indisponible: {exc}")) from exc
    when = parse_iso(body.t) if body.t else _now()
    live = sample_clock_at_time(clock, when)
    if live is None:
        raise HTTPException(400, "pas de position live")
    if live.get("vehicle") in ("plane", "side"):
        raise HTTPException(409, "recalcul désactivé en phase air / relais")
    dest = _next_flag(voy.get("marks") or [], float(live.get("sailNm") or 0),
                      body.to_name)
    if dest is None:
        raise HTTPException(400, "aucune escale à drapeau devant")
    cube = load_cube(voyage_id)
    t0 = parse_iso(voy["t0"])
    from_nm = float(live.get("sailNm") or 0)
    to_nm = float(dest.get("nm") or dest.get("filmNm") or 0)
    searoute = _leg_coords(voy.get("points") or [], from_nm, to_nm)

    # The isochrone calls wind_fn thousands of times: the atlas is warmed once,
    # in parallel and within a budget, then the loop reads the cache only.
    # Cells still missing fall back to the zone climatology (honest label).
    corridor = list(searoute) or [(float(live["lat"]), float(live["lon"]))]
    if dest.get("lat") is not None and dest.get("lon") is not None:
        corridor.append((float(dest["lat"]), float(dest["lon"])))
    months = {when.month, (when + timedelta(days=30)).month}
    prefetch_atlas_cells(corridor_cells(corridor, months), budget_s=ATLAS_PREFETCH_BUDGET_S)
    wind_fn = make_wind_fn(t0, cube, atlas_network=False, now=_now(), hindcast_fn=_hindcast_lookup)
    versus_hours = None
    for m in clock.get("marks") or []:
        if m.get("name") == dest.get("name"):
            versus_hours = max(0.0, float(m["tHours"]) - float(live.get("tHours") or 0))
            break
    versus_nm = max(0.0, to_nm - from_nm)

    if dest.get("lat") is not None and dest.get("lon") is not None:
        dst_lat, dst_lon = float(dest["lat"]), float(dest["lon"])
    elif searoute:
        dst_lat, dst_lon = searoute[-1]
    else:
        dst_lat, dst_lon = float(live["lat"]), float(live["lon"])

    wind_max = body.wind_max_kt if body.wind_max_kt and 10 <= body.wind_max_kt <= 80 else None
    hs_max = body.hs_max_m if body.hs_max_m and 0.5 <= body.hs_max_m <= 12 else None
    from plan_advisor import (  # noqa: PLC0415
        CORRIDOR_MAX_NM,
        DISTANCE_CAP_RATIO,
        advise,
        corridor_track,
        plan_from_current_leg,
        track_nm,
    )
    ref_nm = versus_nm if versus_nm > 0 else track_nm(searoute)
    max_nm = ref_nm * DISTANCE_CAP_RATIO if ref_nm > 0 else None
    chosen = searoute
    plan_advice = None
    try:
        thresholds = {}
        if wind_max is not None:
            thresholds["galeKt"] = wind_max
        if hs_max is not None:
            thresholds["hsAlertM"] = hs_max
        mini = plan_from_current_leg(
            [{"lat": la, "lon": lo} for la, lo in searoute] or [
                {"lat": float(live["lat"]), "lon": float(live["lon"])},
                {"lat": dst_lat, "lon": dst_lon},
            ],
            frm="position", to=str(dest.get("name") or "escale"),
            depart=when if live.get("status") != "waiting" else t0,
            thresholds=thresholds,
        )
        plan_advice = advise(mini, 0, now=when)
        name = (plan_advice.get("best") or {}).get("corridor") or "reference"
        chosen = corridor_track(searoute, name) or searoute
    except Exception as exc:
        log.warning("conseil corridor : %s", exc)
    result = run_leg_isochrone(
        dep_lat=float(live["lat"]),
        dep_lon=float(live["lon"]),
        dst_lat=dst_lat,
        dst_lon=dst_lon,
        departure_time=when if live.get("status") != "waiting" else t0,
        wind_fn=wind_fn,
        polar_raw=_polar_raw(voy.get("expedition_id") or ""),
        searoute_coords=chosen or searoute,
        corridor_coords=searoute or chosen,
        corridor_max_nm=CORRIDOR_MAX_NM if searoute else None,
        max_distance_nm=max_nm,
        wave_nogo_fn=combine_nogo(
            skipper_nogo(wind_fn, wind_max_kt=wind_max, hs_max_m=hs_max),
            amp_nogo_fn(
                load_forbidden_nogo(),
                escape_points=[
                    (float(live["lat"]), float(live["lon"])),
                    (dst_lat, dst_lon),
                ],
            ),
        ),
    )
    old_coords = [[lon, lat] for lat, lon in searoute]
    draft = {
        **result,
        "constraints": {
            "windMaxKt": wind_max,
            "hsMaxM": hs_max if hs_max is not None else WAVE_NOGO_M,
            "source": "skipper" if (wind_max is not None or hs_max is not None) else "default",
        },
        "versus_searoute": {
            "hours": round(versus_hours, 2) if versus_hours is not None else None,
            "distance_nm": round(versus_nm, 2),
        },
        "old_geojson": {
            "type": "Feature",
            "properties": {"role": "searoute-leg"},
            "geometry": {"type": "LineString", "coordinates": old_coords},
        },
        "from_sail_nm": from_nm,
        "to_sail_nm": to_nm,
        "to_name": dest.get("name"),
        "from_lat": live["lat"],
        "from_lon": live["lon"],
    }
    if isinstance(plan_advice, dict) and isinstance(plan_advice.get("best"), dict):
        best = plan_advice["best"]
        draft["planAdvice"] = {
            "leg": plan_advice.get("leg", 0),
            "best": {k: best[k] for k in (
                "shiftDays", "corridor", "extraNm", "score", "sentence",
                "alertsBefore", "alertsAfter", "cascade",
                "totalBefore", "totalAfter", "sentenceLang",
            ) if k in best},
        }
    new_coords = (result.get("draft_geojson") or {}).get("geometry", {}).get("coordinates") or []
    delta = route_delta(
        old_coords, new_coords,
        official_nm=versus_nm,
        recomputed_nm=result.get("distance_nm"),
    )
    try:
        draft["advice"] = _run_async(explain_recompute(delta, draft.get("constraints")))
    except Exception as exc:
        log.warning("explication recalcul : %s", exc)
        facts = advice_facts(delta, draft.get("constraints"))
        draft["advice"] = {"text": advice_fallback(facts), "source": "rules", "delta": facts}
    update_voyage(voyage_id, draft=draft)
    return draft


@router.get("/voyage/{voyage_id}/draft")
def get_draft(voyage_id: str):
    voy = load_voyage(voyage_id)
    if voy is None:
        raise HTTPException(404, "voyage inconnu")
    if not voy.get("draft"):
        raise HTTPException(404, "pas de brouillon")
    return voy["draft"]


@router.post("/voyage/{voyage_id}/accept", dependencies=[Depends(_compute_limited)])
def accept_draft(voyage_id: str):
    if _is_official(voyage_id):
        raise HTTPException(403, "le voyage officiel ne se modifie pas ici")
    voy = load_voyage(voyage_id)
    if voy is None:
        raise HTTPException(404, "voyage inconnu")
    draft = voy.get("draft")
    if not draft:
        raise HTTPException(404, "pas de brouillon")
    coords = (draft.get("draft_geojson") or {}).get("geometry", {}).get("coordinates") or []
    if len(coords) < 2:
        raise HTTPException(400, "brouillon sans géométrie")
    new_points = _splice_points(
        voy.get("points") or [],
        float(draft["from_sail_nm"]),
        float(draft["to_sail_nm"]),
        coords,
    )
    voy["points"] = new_points
    voy["routeRev"] = int(voy.get("routeRev") or 0) + 1
    cube = load_cube(voyage_id)
    try:
        voy["clock"] = _clock_with_cube(voy, cube) if cube else _climo_clock(voy)
    except Exception as exc:
        log.exception("accept: horloge climato échouée")
        raise HTTPException(503, _dated_error(f"horloge climato indisponible: {exc}")) from exc
    voy["draft"] = None
    voy["acceptedAlt"] = draft.get("old_geojson")
    save_voyage(voy)
    return {**_public_meta(voy), "clock": voy["clock"], "points": voy["points"]}


@router.post("/voyage/{voyage_id}/reject", dependencies=[Depends(_compute_limited)])
def reject_draft(voyage_id: str):
    if _is_official(voyage_id):
        raise HTTPException(403, "le voyage officiel ne se modifie pas ici")
    voy = load_voyage(voyage_id)
    if voy is None:
        raise HTTPException(404, "voyage inconnu")
    update_voyage(voyage_id, draft=None)
    return {"ok": True, "voyageId": voyage_id}

