"""NAVIGUIDE simulator API — searoute, polar (sans chat), proxies, vent."""
from __future__ import annotations

import asyncio
import faulthandler
import logging
import math
import os
import re
import signal
import sys
import time

# Diagnostic (RC18) : `kill -USR1 <pid de l'API>` écrit les piles Python de tous les fils sur stderr
# (donc dans .dev/api.log sur le poste, journalctl sur le VPS). Sans root, sans py-spy.
try:
    faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True, chain=False)
except (AttributeError, ValueError, RuntimeError):
    pass
from pathlib import Path
from typing import List, Optional, Union

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

_DIR = Path(__file__).resolve().parent
_SIM_ROOT = _DIR.parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

import httpx

from admin_guard import cors_origins, rate_limited
from bi_proxy import router as bi_proxy_router
from bi_upstream import bi_base
from mem_limits import (
    ZEE_CACHE_MAX_BYTES,
    ZEE_MAX_FEATURES_CAP,
    ZEE_NO_BBOX_MAX_FEATURES,
    ZEE_RESPONSE_MAX_BYTES,
    lru_set,
    too_large,
)
from weather_pipeline import get_pipeline, route_snapshot, route_snapshot_group
from ici_engine import (
    ICI_RADIUS_NM,
    accept_layer_warm,
    empty_dossier,
    fetch_wpi_features,
    fill_dossier,
    layer_warm_status,
    warm_amp_cells_along,
)
from story_cascade import write_story
from polar_api import router as polar_router
from escale_api import router as escale_router
from logbook_chat import router as logbook_router
from route_engine import (
    RouteBusy,
    endpoint_on_land,
    searoute_with_exact_end,
    segment_crosses_land,
    unwrap_path,
    wrap_lon,
)
from spatial_catalog import MAX_RENDER_FEATURES, SpatialCatalogIndex, parse_bbox
from voyage_api import router as voyage_router

log = logging.getLogger("naviguide-simulator")

load_dotenv(_SIM_ROOT / ".env")
from offline import apply_at_startup, enabled as offline_enabled
apply_at_startup()

COPERNICUS_USERNAME = os.getenv("COPERNICUS_USERNAME")
COPERNICUS_PASSWORD = os.getenv("COPERNICUS_PASSWORD")

try:
    from copernicus.getWind import get_wind_data_at_position
    from copernicus.getWave import get_wave_data_at_position
    from copernicus.getCurrent import get_current_data_at_position
except Exception as exc:
    get_wind_data_at_position = None
    get_wave_data_at_position = None
    get_current_data_at_position = None
    print(f"⚠️  Copernicus Marine non chargé ({type(exc).__name__}: {exc})")

app = FastAPI(
    title="NAVIGUIDE simulator",
    description="Cockpit Berry-Mappemonde — hors production.",  # pragma: allowlist secret
    version="0.1.0",
)
# Sécurité P0 : plus de "*" — le client de prod est servi par le même nginx,
# CORS ne concerne que le dev Vite (5174) et les outils. NAVIGUIDE_CORS_ORIGINS
# pour changer la liste sans toucher au code.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Content-Type", "X-Naviguide-Admin"],
)
# 29 sept. : l'horloge officielle (GET /voyage/official/clock, et le PUT /voyage/official qui la porte) pèse
# 3,9 Mo de JSON très répétitif — 335 ko une fois gzippés. Derrière le tunnel du poste de recette, ces 3,9 Mo
# mettaient plus d'une minute et le bateau restait au jour 0 à distance. Le client (navigateur, Cloudflare)
# annonce toujours gzip ; nginx en prod compresse déjà, uvicorn seul ne le faisait pas.
app.add_middleware(GZipMiddleware, minimum_size=2048)
app.include_router(polar_router)
app.include_router(voyage_router)
app.include_router(escale_router)
app.include_router(logbook_router)
# Dev / CI seulement : en prod nginx sert /bi/ avant uvicorn (cache partagé).
app.include_router(bi_proxy_router)


@app.on_event("startup")
def _startup_official_grib():
    """Semis du voyage officiel + travail de fond du stock RF2 — jamais bloquant.

    Sans voyage en base, le stock est vide : l'API répond « en préparation ».
    On sème l'itinéraire Berry embarqué puis le worker remplit le stock hors
    des requêtes. En pytest le semis est coupé (fixtures PUT à 3 points)
    sauf NAVIGUIDE_SEED_OFFICIAL=force.
    """
    try:
        from ici_engine import ensure_pearl_amp_layer_sig  # noqa: PLC0415

        ensure_pearl_amp_layer_sig("api_startup")
    except Exception as exc:
        log.warning("signature de couche : %s", exc)
    try:
        from voyage_api import (
            _auto_seed_official_enabled,
            _kick_official_eta,
            _kick_official_grib,
            _kick_official_hindcast,
            startup_official_voyage,
        )
        if _auto_seed_official_enabled():
            startup_official_voyage()
            return
        _kick_official_grib()
        _kick_official_hindcast()
        _kick_official_eta()
    except Exception as exc:
        log.warning("startup officiel: %s", exc)


@app.on_event("startup")
async def _startup_ici_warm():
    """Perles along de la route officielle : cache disque rechargé, puis
    chauffé en fond (une perle toutes les ~1,2 s). NAVIGUIDE_ICI_WARM=0 coupe.
    Avant, la couche ZEE VLIZ locale : chargée si en cache, sinon
    téléchargée en fond — le chauffeur lit les ZEE en local dès qu'elle est là."""
    try:
        import zee_local
        zee_local.start_background(asyncio.get_running_loop())
    except Exception as exc:
        log.warning("startup ZEE locale: %s", exc)
    try:
        import ici_warm
        ici_warm.start_background(asyncio.get_running_loop())
    except Exception as exc:
        log.warning("startup ici warm: %s", exc)


@app.on_event("startup")
async def _startup_tf_catalog():
    """Garde des modèles Token Factory : une lecture gratuite de `/models` par
    hôte configuré, en fond (jamais en mode LLM off, ni sans clé, ni si
    NAVIGUIDE_TF_MODEL_GUARD=0). Ensuite, relu à l'usage toutes les 6 h."""
    try:
        import llm_budget
        import story_cascade
        import tf_catalog

        key = story_cascade.nebius_key()
        if llm_budget.mode() == "off" or not key or not tf_catalog.enabled():
            return
        bases = [story_cascade.tf_base(t) for t in llm_budget.TIERS]
        asyncio.get_running_loop().create_task(tf_catalog.prefetch(bases, key))
    except Exception as exc:
        log.warning("startup catalogue TF: %s", exc)


def _dated_ici(reason: str, status: str = "unavailable") -> dict:
    return {"status": status, "reason": str(reason), "at": _now_iso()}


def _live_ici_fill() -> bool:
    """True seulement si le chauffeur de perles est allumé (VPS).

    Le poste de recette a NAVIGUIDE_ICI_WARM=0. Un fill_dossier sur /ici ou
    /ici/moment y lisait des tuiles AMP de 7 à 40 Mo dans sqlite : le
    processus dépassait 2 Go, le ramasse-miettes figeait /clock et /film,
    Cloudflare renvoyait 524. Les sacs viennent des perles déjà en stock.
    """
    try:
        import ici_warm
        return ici_warm.warm_enabled()
    except Exception:
        return True


def _bag_ready(bag: dict, lat: float, lon: float) -> dict:
    out = dict(bag)
    out.setdefault("at", {"lat": lat, "lon": lon})
    out["cached"] = True
    out["status"] = out.get("status") or "ready"
    return out


def _serve_ici_bag(bag: dict | None) -> dict | None:
    """The film-script phrase travels on the existing GET /ici bag."""
    if not isinstance(bag, dict):
        return bag
    try:
        from film_script import attach_ici_film_phrases
        return attach_ici_film_phrases(bag)
    except Exception as exc:
        log.debug("filmPhrases /ici: %s", exc)
        out = dict(bag)
        out.setdefault("filmPhrases", {})
        return out


@app.get("/ici/warm/status")
def ici_warm_status():
    """Où en est la pré-génération des perles de la route officielle (+ la couche ZEE locale)."""
    try:
        import ici_warm
        import zee_local
        warm = ici_warm.status()
        stories = warm.get("stories") or {"skipped": "on-demand"}
        return {
            **warm,
            "zeeLocal": zee_local.status(),
            "stories": stories,
            "layers": layer_warm_status(),
        }
    except Exception as exc:
        log.exception("GET /ici/warm/status")
        return _dated_ici(f"préchauffage indisponible: {exc}")


@app.get("/ici/pearls")
def ici_pearls():
    """Les perles canoniques de la route officielle (12 nm) : le client les
    échantillonne aux mêmes positions, ses sacs thin tombent dans le cache."""
    try:
        import ici_warm
        return ici_warm.official_pearls()
    except Exception as exc:
        log.exception("GET /ici/pearls")
        return {"voyageId": None, "pearls": [], "count": 0, **_dated_ici(f"perles indisponibles: {exc}")}


class LayerWarmBody(BaseModel):
    points: list[list[float]] = []


_layer_warm_limited = rate_limited("layer-warm", 8, 60.0)


@app.get("/ici/layers/warm/status")
def ici_layers_warm_status():
    """Où en est le préchauffage des cellules AMP d'un trait dessiné."""
    return layer_warm_status()


@app.post("/ici/layers/warm", dependencies=[Depends(_layer_warm_limited)])
async def post_ici_layers_warm(body: LayerWarmBody, background: BackgroundTasks):
    """Chauffe les cellules AMP 1° le long d'une route perso. Ne bloque pas Terminer."""
    raw = [p for p in (body.points or []) if isinstance(p, (list, tuple)) and len(p) >= 2]
    if len(raw) > 2000:
        step = max(1, math.ceil(len(raw) / 2000))
        raw = raw[::step][:2000]
    out = accept_layer_warm(raw)
    if out.get("accepted"):
        background.add_task(warm_amp_cells_along, raw)
    return out


@app.get("/voyage/official/film")
async def get_official_film(
    lang: str = Query("fr"),
    seconds: int = Query(150, ge=0, le=300),
    style: str = Query("raw"),
    t0: str | None = Query(None),
):
    """Lit le script du film sans lancer de génération."""
    import official_store
    try:
        out = official_store.serve_film(lang=lang, seconds=seconds, style=style)
    except Exception as exc:
        log.exception("GET /voyage/official/film")
        official_store.kick_worker()
        return official_store.preparing_payload("film", {
            "chapters": [], "source": "rules", "chars": 0,
            "targetSeconds": seconds, "hasWritten": False,
            **_dated_ici(f"film indisponible: {exc}", "preparing"),
        })
    if out.get("status") == official_store.PREPARING:
        official_store.kick_worker()
    return out


# Même gabarit que POST /ici/story : 12 / min / IP, 60 / min et 240 / h
# pour tout le serveur. Compteurs séparés, pour qu'un récit ne mange pas
# le budget du film. Pas de clé admin : le bouton public reste ouvert.
_film_write_limited = rate_limited("film-write", 12, 60.0, global_limit=60)
_film_write_hourly = rate_limited("film-write-hour", 10**9, 3600.0, global_limit=240)


@app.post(
    "/voyage/official/film",
    dependencies=[Depends(_film_write_limited), Depends(_film_write_hourly)],
)
async def post_official_film_write(
    lang: str = Query("fr"),
    seconds: int = Query(150, ge=0, le=300),
    style: str = Query("written"),
    t0: str | None = Query(None),
):
    """Clic Rédigé : une chaîne Super / Ultra / Lightning, jamais au GET.

    Durées acceptées : celles que le client envoie vraiment. La barre n'offre
    que 2:30 (150) et 3:00 (180) ; aucun choix envoie 0 (film intégral —
    l'état de départ, et le second clic sur la durée cochée). Le stock ne
    prépare que ces trois clés. Toute autre valeur répond 422. On ne recale
    pas vers la durée la plus proche : le rédigé serait rangé sous une autre
    clé que celle relue ensuite par le GET.
    """
    import official_store
    if int(seconds) not in official_store.FILM_VARIANT_SECONDS:
        raise HTTPException(422, "unsupported film duration")
    try:
        out = await official_store.start_film_write(lang=lang, seconds=seconds)
    except Exception as exc:
        log.exception("POST /voyage/official/film")
        official_store.kick_worker()
        return official_store.preparing_payload("film", {
            "chapters": [], "source": "rules", "chars": 0,
            "targetSeconds": seconds, "hasWritten": False,
            **_dated_ici("all-providers-failed", "preparing"),
        })
    if out.get("status") == official_store.PREPARING:
        official_store.kick_worker()
    return out


class PositionRequest(BaseModel):
    latitude: float
    longitude: float


def _copernicus_ready() -> bool:
    if offline_enabled():
        return False
    return bool(
        COPERNICUS_USERNAME
        and COPERNICUS_PASSWORD
        and get_wind_data_at_position
        and get_wave_data_at_position
        and get_current_data_at_position
    )


def _is_estimated(record: dict | None) -> bool:
    data = (record or {}).get("data") or {}
    return bool(data.get("simulation")) or str(data.get("source") or "").startswith("estimated")


def _mark_live(data: dict) -> dict:
    out = dict(data)
    out.pop("simulation", None)
    out["source"] = "copernicus-marine"
    return out


def _force_estimated(kind: str, lat: float, lon: float) -> bool:
    if not _copernicus_ready():
        return False
    return _is_estimated(get_pipeline().peek(kind, lat, lon))


def _weather_snapshot(kind: str, request: PositionRequest, loader) -> dict:
    lat, lon = request.latitude, request.longitude
    return route_snapshot(
        kind, lat, lon, lambda: loader(request), force=_force_estimated(kind, lat, lon),
    )


@app.get("/")
def health():
    return {"service": "naviguide-simulator", "version": "0.2.0"}


@app.get("/ici")
async def get_ici(
    lat: float = Query(...),
    lon: float = Query(...),
    radius_nm: float = Query(ICI_RADIUS_NM, ge=5, le=40),
    month: int | None = Query(None, ge=1, le=12),
    dest_lat: float | None = Query(None),
    dest_lon: float | None = Query(None),
    thin: bool = Query(False),
):
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(400, "lat/lon hors limites")
    if dest_lat is not None and not (-90 <= dest_lat <= 90):
        raise HTTPException(400, "dest_lat hors limites")
    if dest_lon is not None and not (-180 <= dest_lon <= 180):
        raise HTTPException(400, "dest_lon hors limites")
    # Perle d'abord. Le snapshot officiel (ici_bag_near) est lent, et un
    # fill_dossier sur le poste (WARM=0) chargeait des tuiles AMP de plusieurs Mo.
    pearl = _nearest_warmed_pearl(lat, lon, max_nm=radius_nm)
    if pearl:
        return _serve_ici_bag(_bag_ready(pearl, lat, lon))
    import official_store
    try:
        stored = official_store.ici_bag_near(lat, lon)
        if stored:
            return _serve_ici_bag(_bag_ready(stored, lat, lon))
        if official_store.on_official_route(lat, lon):
            if _live_ici_fill():
                official_store.kick_worker()
            return _serve_ici_bag(official_store.preparing_ici(lat, lon, radius_nm))
    except Exception as exc:
        log.warning("stock /ici: %s", exc)
    if not _live_ici_fill():
        bag = empty_dossier(lat, lon, radius_nm)
        bag.update(_dated_ici("sac en préparation", "preparing"))
        return _serve_ici_bag(bag)
    try:
        return _serve_ici_bag(await fill_dossier(
            lat, lon, radius_nm, month=month, dest_lat=dest_lat, dest_lon=dest_lon, thin=thin,
        ))
    except Exception as exc:
        log.exception("GET /ici")
        bag = empty_dossier(lat, lon, radius_nm)
        bag.update(_dated_ici(f"sac ici indisponible: {exc}"))
        return _serve_ici_bag(bag)


_MOMENT_MODES = frozenset({"follow", "simulation", "drawn"})
_PEARL_LEG_KEYS = (
    "from", "to", "day", "kn", "plannedKnots", "remainingNm", "doneNm",
    "headingDeg", "eta", "regime", "basis", "fromNm", "toNm", "tHours",
)


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _month_from_t(value: str | None) -> int | None:
    from datetime import datetime, timezone
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.month


def _pearl_pos(pearl: dict | None) -> tuple[float, float] | None:
    if not isinstance(pearl, dict):
        return None
    at = pearl.get("at") if isinstance(pearl.get("at"), dict) else {}
    lat = at.get("lat") if at.get("lat") is not None else pearl.get("lat")
    lon = at.get("lon") if at.get("lon") is not None else pearl.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return float(lat), float(lon)
    return None


def _nearest_warmed_pearl(lat: float, lon: float, max_nm: float = ICI_RADIUS_NM) -> dict | None:
    """Perle SQLite la plus proche ; None si le magasin est vide ou trop loin."""
    import pearl_store
    try:
        key, dist = pearl_store.nearest_pearl_key(lat, lon)   # colonnes lat/lon : aucun sac décodé (RC18)
    except Exception:
        return None
    if not key or dist is None or dist > max_nm:
        return None
    row = pearl_store.get_pearl(key)
    bag = (row or {}).get("bag") if isinstance(row, dict) else None
    return bag if isinstance(bag, dict) else None


def _leg_from_pearl(pearl: dict | None) -> dict:
    """Jambe déjà portée par la perle ; vide sinon — plus de greffe official_mini."""
    if not isinstance(pearl, dict):
        return {}
    raw = pearl.get("leg") if isinstance(pearl.get("leg"), dict) else None
    if raw:
        return dict(raw)
    return {key: pearl[key] for key in _PEARL_LEG_KEYS if pearl.get(key) is not None}


def _moment_clock_and_leg(lat: float, lon: float, t: str | None, mode: str, pearl: dict | None):
    """Horloge = requête ; jambe vide sauf champs déjà sur la perle."""
    when = t or _now_iso()
    mode_ok = mode if mode in _MOMENT_MODES else "follow"
    clock = {"iso": when, "t": when, "lat": lat, "lon": lon, "mode": mode_ok}
    thresholds = {"galeKt": 34.0, "hsAlertM": 3.0}
    if isinstance(pearl, dict) and isinstance(pearl.get("skipper_thresholds"), dict):
        thresholds = pearl["skipper_thresholds"]
    return clock, _leg_from_pearl(pearl), thresholds


@app.get("/ici/moment")
async def get_ici_moment(
    lat: float = Query(...),
    lon: float = Query(...),
    t: str | None = Query(None),
    mode: str = Query("follow"),
    lang: str = Query("fr"),
):
    """Moment : perle la plus proche, sinon sac comme /ici, puis build_moment."""
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(400, "lat/lon hors limites")
    from moment import build_moment
    import official_store
    pearl = None
    try:
        pearl = _nearest_warmed_pearl(lat, lon) or official_store.ici_bag_near(lat, lon)
        if pearl is None and official_store.on_official_route(lat, lon):
            if _live_ici_fill():
                official_store.kick_worker()
            pearl = official_store.preparing_ici(lat, lon, ICI_RADIUS_NM)
    except Exception as exc:
        log.warning("stock /ici/moment: %s", exc)
        pearl = None
    if pearl is None and _live_ici_fill():
        try:
            pearl = await fill_dossier(
                lat, lon, ICI_RADIUS_NM, month=_month_from_t(t), dest_lat=None, dest_lon=None, thin=False,
            )
        except Exception as exc:
            log.exception("GET /ici/moment fill_dossier")
            return {
                **_dated_ici(f"moment indisponible: {exc}"),
                "t": t,
                "pos": {"lat": lat, "lon": lon},
                "here": {},
                "alerts": [],
                "around": [],
            }
    if pearl is None:
        pearl = official_store.preparing_ici(lat, lon, ICI_RADIUS_NM)
    try:
        from piracy import attach_piracy  # noqa: PLC0415
        attach_piracy(pearl, lat, lon)
    except Exception as exc:
        log.warning("piracy /ici/moment: %s", exc)
        if isinstance(pearl, dict):
            pearl.setdefault("piracy", None)
    try:
        clock, leg, thresholds = _moment_clock_and_leg(lat, lon, t, mode, pearl)
        return build_moment(pearl, clock, leg, thresholds, lang=lang)
    except Exception as exc:
        log.exception("GET /ici/moment")
        return {
            **_dated_ici(f"moment indisponible: {exc}"),
            "t": t,
            "pos": {"lat": lat, "lon": lon},
            "here": {},
            "alerts": [],
            "around": [],
        }


# Dépense LLM : 12 récits / min / IP, 60 / min et 240 / h pour tout le serveur.
# Le client tombe sur la phrase locale en cas de 429 (storyQueue → failed).
_story_limited = rate_limited("story", 12, 60.0, global_limit=60)
_story_hourly = rate_limited("story-hour", 10**9, 3600.0, global_limit=240)
_weather_limited = rate_limited("weather", 90, 60.0)


@app.post("/ici/story", dependencies=[Depends(_story_limited), Depends(_story_hourly)])
async def post_ici_story(body: dict):
    """Récit d'un événement, uniquement sur un geste « Rédigé ».
    Cache de lecture d'abord, puis cascade Super (tier write). Play n'attend pas."""
    if not isinstance(body, dict) or not (body.get("event") or body.get("eventId")):
        raise HTTPException(400, "événement manquant")
    if len(str(body)) > 60_000:
        raise HTTPException(413, "événement trop volumineux")
    from ai_transparency import enrich_llm_payload
    from story_cache import story_through_cache
    out = await story_through_cache(body, writer=write_story)
    return enrich_llm_payload(out) if isinstance(out, dict) else out


# Longitude dépliée tolérée (un tour et demi) ; au-delà, l'appel est absurde.
ROUTE_LON_LIMIT = 540.0


@app.get("/route")
def get_route(
    start_lat: float = Query(..., ge=-90, le=90),
    start_lon: float = Query(..., ge=-ROUTE_LON_LIMIT, le=ROUTE_LON_LIMIT),
    end_lat: float = Query(..., ge=-90, le=90),
    end_lon: float = Query(..., ge=-ROUTE_LON_LIMIT, le=ROUTE_LON_LIMIT),
    check_wind: bool = Query(False),
):
    # Searoute attend [−180, 180]. Une longitude dépliée (236,84° = SF vue depuis
    # l'Australie) est acceptée jusqu'à ±540° et repliée ici ; au-delà, ou non
    # finie, la validation des paramètres répond 422. On redéplie relativement
    # au départ.
    orig_start_lon = start_lon
    start = (wrap_lon(start_lon), start_lat)
    end = (wrap_lon(end_lon), end_lat)
    # `end` says which point is on land (on_land_start / on_land_end), so the
    # client removes that point and no other.
    for which, (lon_, lat_) in (("on_land_start", start), ("on_land_end", end)):
        if endpoint_on_land(lat_, lon_):
            return JSONResponse(status_code=422, content={"detail": "on_land", "end": which})
    if abs(start[0] - end[0]) < 1e-4 and abs(start[1] - end[1]) < 1e-4:
        return {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": unwrap_path([[start[0], start[1]], [end[0], end[1]]], orig_start_lon),
            },
            "properties": {"length": 0, "units": "km"},
        }
    try:
        route = searoute_with_exact_end(start, end)
        if route is None:
            # searoute really answered « no route »: only then is it land.
            if segment_crosses_land(start[0], start[1], end[0], end[1]):
                raise HTTPException(status_code=422, detail="crosses_land")
            raise HTTPException(status_code=404, detail="Route non trouvée")
        coords = (route.get("geometry") or {}).get("coordinates") or []
        if coords:
            geometry = dict(route.get("geometry") or {})
            geometry["coordinates"] = unwrap_path(coords, orig_start_lon)
            route = {**route, "geometry": geometry}
        return route
    except HTTPException:
        raise
    except RouteBusy as exc:
        # Out of time or of searoute slots: not land, just « try again ».
        raise HTTPException(status_code=503, detail="busy", headers={"Retry-After": "5"}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _sim_wind(lat: float, lon: float) -> dict:
    import datetime
    import random

    rng = random.Random(int(abs(lat * 100) + abs(lon * 100)))
    speed_ms = rng.uniform(3, 18)
    direction = round(rng.uniform(0, 360), 1)
    u = round(-speed_ms * math.sin(math.radians(direction)), 3)
    v = round(-speed_ms * math.cos(math.radians(direction)), 3)
    return {
        "latitude": lat,
        "longitude": lon,
        "u_component": u,
        "v_component": v,
        "wind_speed": round(speed_ms, 2),
        "wind_speed_kmh": round(speed_ms * 3.6, 1),
        "wind_speed_knots": round(speed_ms * 1.944, 1),
        "wind_direction": direction,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "simulation": True,
        "source": "estimated (Copernicus unavailable)",
    }


def _sim_wave(lat: float, lon: float) -> dict:
    import datetime
    import random

    rng = random.Random(int(abs(lat * 137) + abs(lon * 73)))
    return {
        "latitude": lat,
        "longitude": lon,
        "significant_wave_height_m": round(rng.uniform(0.3, 4.5), 2),
        "mean_wave_period": round(rng.uniform(4, 14), 1),
        "mean_wave_direction": round(rng.uniform(0, 360), 1),
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "simulation": True,
        "source": "estimated (Copernicus unavailable)",
    }


def _sim_current(lat: float, lon: float) -> dict:
    import datetime
    import random

    rng = random.Random(int(abs(lat * 211) + abs(lon * 157)))
    speed_ms = rng.uniform(0.05, 1.2)
    direction = round(rng.uniform(0, 360), 1)
    return {
        "latitude": lat,
        "longitude": lon,
        "u_component": round(speed_ms * math.sin(math.radians(direction)), 4),
        "v_component": round(speed_ms * math.cos(math.radians(direction)), 4),
        "speed_ms": round(speed_ms, 3),
        "speed_knots": round(speed_ms * 1.944, 2),
        "speed_kmh": round(speed_ms * 3.6, 2),
        "direction_deg": direction,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "simulation": True,
        "source": "estimated (Copernicus unavailable)",
    }


def _load_wind(request: PositionRequest) -> dict:
    try:
        if COPERNICUS_USERNAME and COPERNICUS_PASSWORD and get_wind_data_at_position:
            wind_data = get_wind_data_at_position(
                latitude=request.latitude,
                longitude=request.longitude,
                username=COPERNICUS_USERNAME,
                password=COPERNICUS_PASSWORD,
            )
            if wind_data is not None:
                return _mark_live(wind_data)
    except Exception as exc:
        print(f"⚠️  Copernicus vent: {type(exc).__name__}: {exc}")
    return _sim_wind(request.latitude, request.longitude)


def _load_wave(request: PositionRequest) -> dict:
    try:
        if COPERNICUS_USERNAME and COPERNICUS_PASSWORD and get_wave_data_at_position:
            wave_data = get_wave_data_at_position(
                latitude=request.latitude,
                longitude=request.longitude,
                username=COPERNICUS_USERNAME,
                password=COPERNICUS_PASSWORD,
            )
            if wave_data is not None:
                return _mark_live(wave_data)
    except Exception as exc:
        print(f"⚠️  Copernicus vague: {type(exc).__name__}: {exc}")
    return _sim_wave(request.latitude, request.longitude)


def _load_current(request: PositionRequest) -> dict:
    try:
        if COPERNICUS_USERNAME and COPERNICUS_PASSWORD and get_current_data_at_position:
            current_data = get_current_data_at_position(
                latitude=request.latitude,
                longitude=request.longitude,
                username=COPERNICUS_USERNAME,
                password=COPERNICUS_PASSWORD,
            )
            if current_data is not None:
                return _mark_live(current_data)
    except Exception as exc:
        print(f"⚠️  Copernicus courant: {type(exc).__name__}: {exc}")
    return _sim_current(request.latitude, request.longitude)


@app.post("/wind", dependencies=[Depends(_weather_limited)])
def get_wind(request: PositionRequest):
    return _weather_snapshot("wind", request, _load_wind)


@app.post("/wave", dependencies=[Depends(_weather_limited)])
def get_wave(request: PositionRequest):
    return _weather_snapshot("wave", request, _load_wave)


@app.post("/current", dependencies=[Depends(_weather_limited)])
def get_current(request: PositionRequest):
    return _weather_snapshot("current", request, _load_current)


@app.post("/weather", dependencies=[Depends(_weather_limited)])
def get_weather(request: PositionRequest):
    """Réponse immédiate : vent / vague / courant, cache cellule + cycle."""
    lat, lon = request.latitude, request.longitude
    force = any(_force_estimated(kind, lat, lon) for kind in ("wind", "wave", "current"))
    return route_snapshot_group(
        (
            ("wind", "wind", lambda: _load_wind(PositionRequest(latitude=lat, longitude=lon))),
            ("wave", "wave", lambda: _load_wave(PositionRequest(latitude=lat, longitude=lon))),
            ("current", "current", lambda: _load_current(PositionRequest(latitude=lat, longitude=lon))),
        ),
        lat,
        lon,
        force=force,
    )


@app.get("/weather/forecast")
def get_forecast_weather(lat: float = Query(...), lon: float = Query(...)):
    """Sac ICI Open-Meteo + RTOFS, même pipeline (pending immédiat)."""
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(400, "lat/lon hors limites")
    from ici_layers import snapshot_ici_weather
    return snapshot_ici_weather(lat, lon)


_WPI_CACHE_TTL = 86_400
_zee_cache: dict = {"entries": {}}
_ZEE_CACHE_TTL = 86_400
_VLIZ_WMS = "https://geo.vliz.be/geoserver/MarineRegions/wms"
_CATALOG_SOURCE_TTL = 900.0
_CATALOG_PATHS = {
    "projects": "/export/geojson",
    "marinas": "/export/marinas.geojson",
    "capitaineries": "/export/capitaineries.geojson",
    "poe": "/export/poe.geojson",
    "amp": "/export/amp.geojson",
    "science": "/export/science.geojson",
}
_catalog_cache: dict[str, dict] = {}
_catalog_tasks: dict[str, asyncio.Task] = {}
_WMS_CACHE_HEADERS = {
    "Cache-Control": "public, max-age=21600, stale-while-revalidate=86400",
}
_SEAMARK_CACHE_HEADERS = {
    "Cache-Control": "public, max-age=86400, stale-while-revalidate=604800",
}

_DMS_RE = re.compile(
    r"""(\d+)\s*[°d]\s*(\d+)\s*[''′]\s*(\d+(?:\.\d+)?)\s*[""″]?\s*([NSEW]?)""",
    re.IGNORECASE,
)


def _parse_coord(value: Optional[Union[str, float, int]]) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    m = _DMS_RE.search(s)
    if m:
        deg, mins, secs, hemi = m.groups()
        decimal = float(deg) + float(mins) / 60.0 + float(secs) / 3600.0
        if hemi.upper() in ("S", "W"):
            decimal = -decimal
        return decimal
    return None


@app.get("/proxy/zee/wms")
async def proxy_zee_wms(request: Request):
    params = dict(request.query_params)
    bbox = params.get("bbox") or params.get("BBOX")
    if not bbox:
        raise HTTPException(status_code=400, detail="Missing bbox parameter")
    params.setdefault("service", "WMS")
    params.setdefault("version", "1.1.1")
    params.setdefault("request", "GetMap")
    params["layers"] = "eez_boundaries"
    params.setdefault("format", "image/png")
    params.setdefault("transparent", "true")
    params.setdefault("srs", "EPSG:3857")
    params.setdefault("width", "512")
    params.setdefault("height", "512")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(_VLIZ_WMS, params=params)
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"VLIZ WMS HTTP {resp.status_code}")
            return Response(content=resp.content, media_type="image/png", headers=_WMS_CACHE_HEADERS)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ZEE WMS error: {exc}") from exc


@app.get("/zee/at")
def zee_at_point(lat: float = Query(...), lon: float = Query(...)):
    """EEZ at one position (film timestep). Local polygons only — no gazetteer."""
    if not math.isfinite(lat) or not math.isfinite(lon) or abs(lat) > 90:
        raise HTTPException(status_code=400, detail="lat/lon")
    import zee_local
    return zee_local.zee_at_payload(lat, lon)


@app.get("/proxy/zee")
async def proxy_zee(
    bbox: Optional[str] = Query(None),
    maxFeatures: int = Query(80, ge=1, le=ZEE_MAX_FEATURES_CAP),
):
    if not bbox and maxFeatures > ZEE_NO_BBOX_MAX_FEATURES:
        raise HTTPException(400, "bbox (minlon,minlat,maxlon,maxlat) requis pour les ZEE")
    cache_key = bbox or f"nobbox:{maxFeatures}"
    cached = _zee_cache.get("entries") or {}
    hit = cached.get(cache_key)
    if hit and (time.time() - hit["ts"] < _ZEE_CACHE_TTL):
        return JSONResponse(content=hit["data"])
    params: dict = {
        "service": "WFS",
        "version": "1.1.0",
        "request": "GetFeature",
        "typeName": "eez",
        "outputFormat": "application/json",
        "maxFeatures": maxFeatures,
    }
    if bbox:
        params["bbox"] = bbox
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.get(
                "https://geo.vliz.be/geoserver/MarineRegions/wfs",
                params=params,
            )
            resp.raise_for_status()
            raw = resp.content or b""
            if too_large(len(raw), ZEE_RESPONSE_MAX_BYTES):
                raise HTTPException(502, f"ZEE upstream trop volumineux ({len(raw)} octets)")
            data = resp.json()
            if bbox and not too_large(len(raw), ZEE_CACHE_MAX_BYTES):
                lru_set(_zee_cache.setdefault("entries", {}), cache_key, {"data": data, "ts": time.time()}, max_items=4)
            return JSONResponse(content=data)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ZEE upstream error: {exc}") from exc


def _parse_ports_bbox(raw: Optional[str]) -> Optional[tuple[float, float, float, float]]:
    try:
        bbox = parse_bbox(raw)
    except ValueError as exc:
        raise HTTPException(400, "bbox ports invalide") from exc
    return None if bbox is None else (bbox.west, bbox.south, bbox.east, bbox.north)


def _port_in_bbox(feature: dict, bbox: Optional[tuple[float, float, float, float]]) -> bool:
    if bbox is None:
        return True
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    if len(coords) < 2:
        return False
    lon, lat = float(coords[0]), float(coords[1])
    west, south, east, north = bbox
    if lat < south or lat > north:
        return False
    copies = (lon - 360.0, lon, lon + 360.0)
    if west <= east:
        return any(west <= value <= east for value in copies)
    return any(value >= west or value <= east for value in copies)


def _catalog_upstream() -> str | None:
    """NAVIGUIDE_CATALOG_UPSTREAM if set, otherwise BI_API_URL. None when both are empty."""
    explicit = (os.getenv("NAVIGUIDE_CATALOG_UPSTREAM") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    return bi_base()


async def _fetch_catalog_features(catalog: str) -> list[dict]:
    """Lit une source explicitement autorisée; aucune URL utilisateur n'est proxifiée."""
    if catalog == "ports":
        return await fetch_wpi_features()
    path = _CATALOG_PATHS.get(catalog)
    if not path:
        raise KeyError(catalog)
    base = _catalog_upstream()
    if not base:
        raise RuntimeError("BI disabled: BI_API_URL is not set")
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{base}{path}", headers={"Accept": "application/geo+json, application/json"})
        response.raise_for_status()
        if too_large(len(response.content), ZEE_RESPONSE_MAX_BYTES):
            raise ValueError("catalogue source trop volumineux")
        payload = response.json()
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise ValueError("catalogue source GeoJSON invalide")
    return features


async def _load_catalog_index(catalog: str) -> SpatialCatalogIndex:
    now = time.monotonic()
    cached = _catalog_cache.get(catalog)
    if cached and now - cached["at"] < _CATALOG_SOURCE_TTL:
        return cached["index"]

    task = _catalog_tasks.get(catalog)
    if task is None:
        task = asyncio.create_task(_fetch_catalog_features(catalog))
        _catalog_tasks[catalog] = task
    try:
        features = await asyncio.shield(task)
    except Exception:
        if cached:
            return cached["index"]
        raise
    finally:
        if _catalog_tasks.get(catalog) is task and task.done():
            _catalog_tasks.pop(catalog, None)

    index = SpatialCatalogIndex(catalog, features)
    _catalog_cache[catalog] = {"at": time.monotonic(), "index": index}
    return index


async def _catalog_feature_collection(
    catalog: str,
    bbox: Optional[str],
    zoom: float,
    limit: int,
    source: Optional[str] = None,
) -> dict:
    if catalog != "ports" and catalog not in _CATALOG_PATHS:
        raise HTTPException(404, "catalogue inconnu")
    try:
        parsed_bbox = parse_bbox(bbox)
    except ValueError as exc:
        raise HTTPException(400, "bbox catalogue invalide") from exc
    if parsed_bbox is None:
        raise HTTPException(400, "bbox (minlon,minlat,maxlon,maxlat) requise")
    try:
        index = await _load_catalog_index(catalog)
    except KeyError as exc:
        raise HTTPException(404, "catalogue inconnu") from exc
    except ValueError as exc:
        raise HTTPException(502, detail=f"catalogue source invalide: {exc}") from exc
    except Exception as exc:
        raise HTTPException(502, detail=f"catalogue source indisponible: {exc}") from exc
    return index.query(parsed_bbox, zoom=zoom, limit=limit, source=source)


@app.get("/proxy/catalog/{catalog}")
async def proxy_catalog(
    catalog: str,
    bbox: str = Query(...),
    zoom: float = Query(2, ge=0, le=18),
    limit: int = Query(MAX_RENDER_FEATURES, ge=1, le=MAX_RENDER_FEATURES),
    source: Optional[str] = Query(None, max_length=40),
):
    """API bbox locale pour les catalogues affichés par le simulateur."""
    data = await _catalog_feature_collection(catalog, bbox, zoom, limit, source)
    return JSONResponse(
        content=data,
        headers={"Cache-Control": "public, max-age=180, stale-while-revalidate=600"},
    )


@app.get("/proxy/ports")
async def proxy_ports(
    bbox: str = Query(...),
    zoom: float = Query(2, ge=0, le=18),
    limit: int = Query(MAX_RENDER_FEATURES, ge=1, le=MAX_RENDER_FEATURES),
):
    # Compatibilité de l'URL historique, désormais servie par le même index.
    visible = await _catalog_feature_collection("ports", bbox, zoom, limit)
    return JSONResponse(
        content=visible,
        headers={"Cache-Control": "public, max-age=180, stale-while-revalidate=600"},
    )


_OPENSEAMAP_HOSTS = ["tiles.openseamap.org", "t1.openseamap.org"]


def _transparent_tile_256() -> bytes:
    try:
        import io
        from PIL import Image

        img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except ImportError:
        return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"


_TRANSPARENT_TILE = None


def _get_transparent_tile() -> bytes:
    global _TRANSPARENT_TILE
    if _TRANSPARENT_TILE is None:
        _TRANSPARENT_TILE = _transparent_tile_256()
    return _TRANSPARENT_TILE


@app.get("/proxy/seamark/{z:int}/{x:int}/{y}.png")
async def proxy_seamark(z: int, x: int, y: str):
    try:
        y_int = int(y)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tile y")
    async with httpx.AsyncClient(timeout=12.0) as client:
        for host in _OPENSEAMAP_HOSTS:
            url = f"https://{host}/seamark/{z}/{x}/{y_int}.png"
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return Response(content=resp.content, media_type="image/png", headers=_SEAMARK_CACHE_HEADERS)
            except Exception:
                continue
    return Response(content=_get_transparent_tile(), media_type="image/png", headers=_SEAMARK_CACHE_HEADERS)
