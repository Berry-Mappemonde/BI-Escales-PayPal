"""Trajet RÉEL figé du voyage officiel.

Le PASSÉ (du départ au dernier jour ERA5 publié, ~5 j de retard) est intégré
jour après jour avec la météo réellement rencontrée (vent ERA5 → polaire ×
0,85 × facteur vagues — mêmes règles que `build_voyage_clock` ; escales et
vol inchangés), puis FIGÉ : l'archive ERA5 est immuable, re-courir
l'intégration redonne exactement les mêmes sommets — un nouveau jour publié
ne fait qu'AJOUTER des sommets. L'AVENIR part de la dernière position réelle
avec la climatologie (atlas), recalculé seulement si la couverture atlas ne
s'est pas dégradée — sinon on sert l'horloge de la veille et le statut le dit.

Les cellules ERA5 sont demandées au fur et à mesure de l'intégration
(fenêtre [jour−3, jour+3] par cellule, un appel) : c'est le trajet réel qui
fixe le besoin, jamais le jour de passage d'une horloge climatologique.
Aucune donnée inventée : pas de vent réel → l'intégration s'arrête là.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from hindcast import (
    ERA5_PRODUCTS,
    OpenMeteoQuotaExceeded,
    at as hindcast_at,
    fill_era5_window,
    hindcast_enabled,
    migrate_orphans_once,
    om_quota_blocked,
    om_quota_reason,
)
from pearl_store import kv_get, kv_put
from longitude import unwrap_lon as _unwrap_lon
from voyage_clock import WindExhausted, _r4, build_voyage_clock, parse_iso, to_iso

log = logging.getLogger("naviguide-simulator.real-track")

NS = "real-track"
KEY = "official"
# ERA5 (archive Open-Meteo) publie avec ~5 jours de retard ; au-delà de
# LAG + 2 jours manquants, le statut passe de ready à partial.
ERA5_PUBLISH_LAG_DAYS = 6
READY_SLACK_DAYS = 2
# L'avenir n'est recalculé que si la couverture atlas ne recule pas (± 2 %).
ATLAS_RATIO_TOLERANCE = 0.02

REASON_QUOTA = "quota Open-Meteo"
REASON_OUTAGE = "panne"
REASON_UNPUBLISHED = "pas encore publié"


def polar_signature(polar_raw: Optional[dict]) -> str:
    if not polar_raw:
        return "none"
    raw = json.dumps(polar_raw, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _as_utc(now: datetime) -> datetime:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _strict_era5_wind(now: datetime, *, fetch: bool = True):
    """wind_fn pour l'intégration réelle : ERA5 du cache, sinon UNE fenêtre
    par cellule, sinon `WindExhausted` — jamais une climatologie étiquetée
    « hindcast », jamais un jour déjà en cache redemandé."""
    limit = _as_utc(now)

    def wind_fn(lat: float, lon: float, t: datetime) -> Dict[str, Any]:
        when = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        if when >= limit:
            raise WindExhausted(None)  # le présent : le passé est à jour
        pack = hindcast_at(lat, lon, when, products=ERA5_PRODUCTS, fetch=False)
        if pack.get("speedKnots") is not None:
            return pack
        if not fetch:
            raise WindExhausted(om_quota_reason() or REASON_UNPUBLISHED)
        if om_quota_blocked():
            raise WindExhausted(REASON_QUOTA)
        try:
            got = fill_era5_window(lat, lon, when)
        except OpenMeteoQuotaExceeded:
            raise WindExhausted(REASON_QUOTA) from None
        pack = hindcast_at(lat, lon, when, products=ERA5_PRODUCTS, fetch=False)
        if pack.get("speedKnots") is not None:
            return pack
        if got is None:
            raise WindExhausted(REASON_OUTAGE)
        raise WindExhausted(REASON_UNPUBLISHED)

    return wind_fn


def _is_real_vertex(v: dict) -> bool:
    return (v.get("regime") or v.get("kind")) == "hindcast"


def ensure_track(voy: dict, now: datetime, polar_raw: Optional[dict],
                 *, fetch: bool = True) -> Optional[dict]:
    """(Re)intègre le trajet réel et le range (kv `real-track`). Append-only :
    l'archive ERA5 étant immuable, re-courir donne les mêmes sommets ; on le
    vérifie et on signale tout recalcul complet (route ou polaire changée).

    Retourne l'état (horloge tronquée + empreintes) ou None si aucun vent
    réel n'est disponible (le poste sert alors l'horloge climatologique)."""
    if not hindcast_enabled():
        return None
    pts = voy.get("points") or []
    if not pts or not voy.get("t0"):
        return None
    migrate_orphans_once()
    clock = build_voyage_clock(
        pts,
        voy.get("marks") or [],
        voy["t0"],
        polar_raw=polar_raw,
        start_at=voy.get("startAt") or "la-rochelle",
        wind_fn=_strict_era5_wind(now, fetch=fetch),
    )
    verts = clock.get("vertices") or []
    if not any(_is_real_vertex(v) for v in verts):
        return None

    state = {
        "routeFp": _route_fp(voy),
        "polarSig": polar_signature(polar_raw),
        "clock": clock,
        "updatedAt": to_iso(_as_utc(now)),
    }
    prev = ((kv_get(NS, KEY) or {}).get("value")) or None
    appended = len(verts)
    recomputed = False
    if isinstance(prev, dict) and isinstance((prev.get("clock") or {}).get("vertices"), list):
        pv = prev["clock"]["vertices"]
        same_base = prev.get("routeFp") == state["routeFp"] and prev.get("polarSig") == state["polarSig"]
        if same_base and pv == verts[: len(pv)]:
            appended = len(verts) - len(pv)
        else:
            recomputed = True
            why = "route officielle ou polaire changée" if not same_base else "sommets passés différents"
            log.warning("trajet réel : RECALCUL COMPLET (%s) — %s sommets", why, len(verts))
    state["appended"] = appended
    state["recomputed"] = recomputed
    kv_put(NS, KEY, state)
    log.info("trajet réel : %s sommets, +%s, réel jusqu'au %s (%s)",
             len(verts), appended, real_until(state, now),
             (clock.get("truncated") or {}).get("reason") or "à jour")
    return state


def _route_fp(voy: dict) -> str:
    from official_store import route_fingerprint  # noqa: PLC0415
    return route_fingerprint(voy)


def real_until(track: dict, now: datetime) -> Optional[str]:
    """Dernier jour RÉEL (date du dernier sommet hindcast, bornée à aujourd'hui)."""
    clock = (track or {}).get("clock") or {}
    verts = [v for v in clock.get("vertices") or [] if _is_real_vertex(v)]
    if not verts:
        return None
    last = parse_iso(verts[-1]["iso"]).date()
    today = _as_utc(now).date()
    return min(last, today).strftime("%Y-%m-%d")


def status_fields(track: Optional[dict], voy: dict, now: datetime) -> dict:
    """Statut honnête du passé réel : ready / partial n/total / empty + raison.

    n = jours intégrés avec la météo réelle, total = jours attendus (du départ
    au dernier jour ERA5 publiable, ~LAG jours avant aujourd'hui). Jamais
    « ready » à vide."""
    try:
        t0 = parse_iso(voy.get("t0") or "")
    except Exception:
        t0 = None
    today = _as_utc(now).date()
    expected_last = today - timedelta(days=ERA5_PUBLISH_LAG_DAYS)
    until = real_until(track, now) if track else None
    reason = None
    if track:
        reason = ((track.get("clock") or {}).get("truncated") or {}).get("reason")
    if not until or t0 is None:
        total = max(0, (expected_last - t0.date()).days + 1) if t0 else 0
        return {
            "hindcastStatus": "empty",
            "hindcastCoverage": f"0/{total}",
            "hindcastReason": reason or (om_quota_reason() if om_quota_blocked() else None) or REASON_OUTAGE,
            "realUntil": None,
        }
    n = max(0, (parse_iso(f"{until}T00:00:00Z").date() - t0.date()).days + 1)
    total = max(n, (expected_last - t0.date()).days + 1)
    if total - n <= READY_SLACK_DAYS and n > 0:
        status, reason = "ready", None
    else:
        status = "partial"
        reason = reason or REASON_UNPUBLISHED
    return {
        "hindcastStatus": status,
        "hindcastCoverage": f"{n}/{total}",
        "hindcastReason": reason,
        "realUntil": until,
    }


def future_clock(voy: dict, track: dict, polar_raw: Optional[dict]) -> Optional[dict]:
    """Horloge climatologique du reste de la route, depuis la dernière position
    réelle. None si le trajet réel couvre déjà toute la route."""
    clock = track.get("clock") or {}
    trunc = clock.get("truncated")
    verts = clock.get("vertices") or []
    if not trunc or not verts:
        return None
    pts = voy.get("points") or []
    i = int(trunc.get("pointIndex") or 0)
    seam_cum = float(trunc.get("pointCumNm") or 0)
    last = verts[-1]
    tail = [dict(p) for p in pts[i + 1:]]
    seam_lon = float(last["lon"])
    if tail and isinstance(tail[0].get("lon"), (int, float)):
        # Sommets repliés [-180, 180], points de route dépliés : la couture
        # reprend la longitude dépliée du point suivant (pas de saut de 360°).
        seam_lon = _unwrap_lon(float(tail[0]["lon"]), seam_lon)
    seam_pt = {
        "lat": last["lat"],
        "lon": seam_lon,
        "cumNm": seam_cum,
        "filmCum": float(trunc.get("pointFilmCum") or seam_cum),
        "jump": False,
        "nonMaritime": False,
    }
    rest = [seam_pt] + tail
    marks = []
    for m in voy.get("marks") or []:
        if float(m.get("nm") or m.get("filmNm") or 0) <= seam_cum + 0.01:
            continue
        m = dict(m)
        # `index` vise la route complète ; `rest[k]` = `pts[i + k]` (k >= 1).
        # Sans ce recalage, Nouméa (index 620) tombait sur pts[i + 620], dans
        # le golfe de Gascogne, et son ETA passait en mai 2027.
        idx = m.get("index")
        if isinstance(idx, int) and not isinstance(idx, bool):
            local = idx - i
            if 1 <= local < len(rest):
                m["index"] = local
            else:
                m.pop("index", None)
        marks.append(m)
    return build_voyage_clock(
        rest, marks, last["iso"], polar_raw=polar_raw, start_at="seam",
    )


def atlas_ratio(future: Optional[dict]) -> float:
    """Part des pas de voile de l'avenir servis par l'atlas (1.0 = couverture
    complète ; le repli par zones fait baisser)."""
    verts = [
        v for v in ((future or {}).get("vertices") or [])
        if v.get("vehicle") == "main" and (v.get("speedKnots") or 0) > 0
    ]
    if not verts:
        return 1.0
    zones = sum(1 for v in verts if v.get("source") == "zone_fallback")
    return 1.0 - zones / len(verts)


def accept_future(ratio: float, previous_ratio: Optional[float]) -> bool:
    """Complet, premier calcul, ou pas pire que la veille (± 2 %)."""
    if ratio >= 0.999:
        return True
    if previous_ratio is None:
        return True
    return ratio >= float(previous_ratio) - ATLAS_RATIO_TOLERANCE


def assemble_clock(track: dict, future: Optional[dict]) -> dict:
    """Horloge complète : sommets réels figés + avenir climatologique recalé
    (tHours, seaHours, sailNm continus ; iso déjà absolus)."""
    clock = track.get("clock") or {}
    tv = list(clock.get("vertices") or [])
    out = {
        "t0": clock.get("t0"),
        "kind": clock.get("kind") or "mixed",
        "vertices": tv,
        "marks": list(clock.get("marks") or []),
        "seaHours": clock.get("seaHours"),
        "quayHours": clock.get("quayHours"),
        "arrivalIso": clock.get("arrivalIso"),
        "startAt": clock.get("startAt"),
    }
    if not future or not tv:
        return out
    seam = tv[-1]
    seam_t = float(seam.get("tHours") or 0)
    seam_sea = float(seam.get("seaHours") or 0)
    sail_delta = float(seam.get("sailNm") or 0) - float(
        (clock.get("truncated") or {}).get("pointCumNm") or 0)
    fv = list(future.get("vertices") or [])
    shifted: List[dict] = []
    for v in fv[1:]:  # le 1er sommet de l'avenir double la couture
        shifted.append({
            **v,
            "tHours": _r4(float(v.get("tHours") or 0) + seam_t),
            "seaHours": _r4(float(v.get("seaHours") or 0) + seam_sea),
            "sailNm": _r4(float(v.get("sailNm") or 0) + sail_delta),
        })
    out["vertices"] = tv + shifted
    out["marks"] = out["marks"] + [
        {**m, "tHours": _r4(float(m.get("tHours") or 0) + seam_t)}
        for m in (future.get("marks") or [])
    ]
    out["seaHours"] = _r4(seam_sea + float(future.get("seaHours") or 0))
    out["quayHours"] = _r4(float(clock.get("quayHours") or 0) + float(future.get("quayHours") or 0))
    out["arrivalIso"] = future.get("arrivalIso") or out["arrivalIso"]
    kinds = {(v.get("regime") or v.get("kind")) for v in out["vertices"] if v.get("regime") or v.get("kind")}
    out["kind"] = "hindcast" if kinds <= {"hindcast"} else ("mixed" if "hindcast" in kinds else "climatology")
    return out
