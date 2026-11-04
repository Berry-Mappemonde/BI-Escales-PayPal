"""Pré-génération des perles along de la route officielle (plan §1.3).

Le film joue à 15–175 nm/s ; un sac `/ici` met 1–8 s. Les événements du film
viennent donc des perles — les mêmes pour tous les visiteurs. Ce module :

- garde les perles dans la base embarquée (`pearl_store`, SQLite dans
  `voyage_data/`), rechargées à la demande ; l'ancien `ici_thin_cache.json`
  est migré une fois au démarrage ;
- au démarrage, **chauffe** les perles **riches** de la route officielle
  (toutes les couches sans horodatage : ZEE, ports d'entrée, AMP, ports,
  projets, fiches science, mouillages, balisage, EMODnet), une tous les
  SAMPLE_NM (12 nm), à un rythme doux (1 perle / WARM_PAUSE_S) —
  MarineRegions et Overpass ne sont appelés qu'une fois par cellule.

`NAVIGUIDE_ICI_WARM=0` désactive le chauffeur (tests, dev sans réseau).
La veille Tavily est active par défaut ; `NAVIGUIDE_TAVILY_WATCH=0` la désactive :
première passe 2 min après le démarrage, puis toutes les
`NAVIGUIDE_TAVILY_WATCH_S` secondes (défaut 86 400). Une recherche par
escale, fenêtre J-10 → J+2. Cette boucle ne parcourt pas les perles.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from longitude import interp_lon_shortest, wrap_lon as _wrap_lon

log = logging.getLogger("naviguide-simulator.ici-warm")

SAMPLE_NM = 12.0
# A rich pearl costs ~4-8 s upstream (MarineRegions + BI + Overpass + EMODnet);
# the pause on top keeps Overpass at well under one request a second.
WARM_PAUSE_S = float(os.environ.get("NAVIGUIDE_ICI_WARM_PAUSE_S") or 1.0)
WARM_PARALLEL = max(1, int(os.environ.get("NAVIGUIDE_ICI_WARM_PARALLEL") or 2))
LEGACY_TTL_S = 7 * 86400.0
POE_NEARBY_NM = 15.0  # a port of entry this close to a pearl was "passed" (journal)
COAST_NEAR_NM = 25.0  # ports / WPI → jalon de côte
SCI_NEARBY_NM = 10.0  # station / campagne scientifique « croisée » (journal)
AMP_NEAR_NM = 30.0    # AMP réelle à portée — repli export (centroïde, RG3)
AMP_NEARBY_NM = 15.0  # polygone : proximité à la limite, hors inside
_AMP_NAME_SPLIT = re.compile(r"\s+[-—–]\s+|\s*\(")
PROJECT_NEAR_NM = 30.0  # projet Blue Intelligence à portée
CLIMO_ROSE_TURN_DEG = 90.0
CLIMO_CALM_KN = 8.0

_state: dict[str, Any] = {
    "status": "idle",  # idle | running | done | disabled | error
    "kind": "rich",
    "total": 0,
    "done": 0,
    "cached": 0,
    "errors": 0,
    "startedAt": None,
    "finishedAt": None,
}


def cache_path() -> Path:
    """The former JSON cache — only read once, to migrate it into SQLite."""
    from voyage_store import voyage_dir
    return voyage_dir() / "ici_thin_cache.json"


def warm_enabled() -> bool:
    return (os.environ.get("NAVIGUIDE_ICI_WARM") or "1").strip() not in ("0", "false", "no")


def stories_enabled() -> bool:
    """Plus de pré-génération de récits d'événements. Toujours faux —
    un réglage NAVIGUIDE_STORY_PREGEN ne peut plus rallumer ~177 appels Super."""
    return False


def watch_enabled() -> bool:
    """Veille Tavily. Active par défaut ; `NAVIGUIDE_TAVILY_WATCH=0` la désactive."""
    import escale_watch  # noqa: PLC0415

    return escale_watch.watch_enabled()


# 15 oct. (porteur) : une passe par jour suffit — une escale n'est cherchée qu'une fois (escale_watch, `done:<slug>`),
# la passe ne sert qu'à attraper les escales qui ENTRENT dans la fenêtre J-10 → J+2. Avant : toutes les 6 h.
WATCH_LOOP_S = float(os.environ.get("NAVIGUIDE_TAVILY_WATCH_S") or 24 * 3600)


def status() -> dict[str, Any]:
    import llm_budget  # noqa: PLC0415
    import pearl_store  # noqa: PLC0415
    info = pearl_store.info()
    out = {
        **_state,
        "store": info,
        "llm": llm_budget.status(),
        "tfQuota": llm_budget.tokenfactory_quota_status(),
        "moments": info.get("moments", 0),
    }
    out.setdefault("stories", {"skipped": "on-demand"})
    try:
        import pearls_warm  # noqa: PLC0415
        out["pearlsWarm"] = pearls_warm.public_status()
    except Exception:
        out["pearlsWarm"] = {
            "state": "idle",
            "done": 0,
            "skipped": 0,
            "remaining": 0,
            "llmSkipped": 0,
            "lastError": None,
            "found": None,
            "routePoints": None,
        }
    return out


def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def sample_route_nm(points: list[dict], step_nm: float = SAMPLE_NM) -> list[dict]:
    """Pearls every `step_nm` along the sea points, interpolated inside long
    segments (the official route has ~32 nm between points). Land legs and
    air hops are skipped; each sea stretch starts with its own pearl.
    Each pearl carries `sailNm` on the **clock's scale** — the route point's
    `cumNm` (which counts the land leg Saint-Maur → La Rochelle, as the clock
    does), interpolated inside a segment. Without `cumNm`, sea miles are
    accumulated from the first sea point."""
    out: list[dict] = []
    if not points:
        return out
    prev = None
    prev_cum = 0.0
    carry = 0.0  # distance since the last pearl
    sail = 0.0   # accumulated sea miles (fallback scale)
    for p in points:
        try:
            lat, lon = float(p["lat"]), float(p["lon"])
        except Exception:
            continue
        if p.get("nonMaritime") or p.get("jump"):
            prev = None
            continue
        cum = p.get("cumNm")
        cum = float(cum) if isinstance(cum, (int, float)) else None
        if prev is None:
            base = cum if cum is not None else sail
            out.append({"lat": lat, "lon": _wrap_lon(lon), "sailNm": round(base, 2)})
            carry = 0.0
            prev = (lat, lon)
            prev_cum = base
            continue
        seg = _haversine_nm(prev[0], prev[1], lat, lon)
        if seg <= 0:
            continue
        pos = step_nm - carry  # distance along this segment to the next pearl
        while pos <= seg:
            t = pos / seg
            out.append({
                "lat": prev[0] + (lat - prev[0]) * t,
                "lon": interp_lon_shortest(prev[1], lon, t),
                "sailNm": round(prev_cum + pos, 2),
            })
            pos += step_nm
        carry = seg - (pos - step_nm)
        sail += seg
        prev = (lat, lon)
        prev_cum = cum if cum is not None else prev_cum + seg
    return out


def sample_route(points: list[dict], step_nm: float = SAMPLE_NM) -> list[tuple[float, float]]:
    """Positions only (warmer, GET /ici/pearls)."""
    return [(p["lat"], p["lon"]) for p in sample_route_nm(points, step_nm)]


def _run_coro(factory):
    """Run `factory()` → coroutine from a sync handler.

    `factory` is called in the thread that owns the event loop, so the
    coroutine is never started on one loop and awaited on another.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    result: dict[str, Any] = {}

    def _in_thread() -> None:
        try:
            result["value"] = asyncio.run(factory())
        except Exception as exc:  # noqa: BLE001 — caller skips the pearl
            result["error"] = exc

    thread = threading.Thread(target=_in_thread, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def get_pearl_bag(lat: float, lon: float, *, rich: bool = True) -> dict | None:
    """Sac `/ici` d'une perle : cache d'abord, sinon fill **sans LLM**.

    None si le fill lève — l'appelant saute la perle. Ne passe pas par
    `fill_dossier` (juge de vérité / veille) : `NAVIGUIDE_LLM_MODE` indifférent.
    Le chauffeur officiel (`warm_official_route`) n'est pas modifié.
    """
    from ici_engine import (  # noqa: PLC0415
        _fill_dossier,
        thin_cache_get,
        thin_cache_key,
        thin_cache_put,
    )

    key = thin_cache_key(lat, lon, 30.0)
    cached = thin_cache_get(key, rich=False)
    if cached is not None:
        if not rich:
            return cached
        rich_hit = thin_cache_get(key, rich=True)
        return rich_hit if rich_hit is not None else cached
    try:
        bag = _run_coro(lambda: _fill_dossier(
            lat, lon, 30.0, None, None, None, None, True, rich,
        ))
    except Exception as exc:
        log.debug("sac /ici %.4f,%.4f : %s", lat, lon, exc)
        return None
    if not isinstance(bag, dict):
        return None
    try:
        thin_cache_put(key, bag, "rich" if rich else "thin", lat, lon)
    except Exception:
        pass
    return bag


def _angle_delta_deg(a: float, b: float) -> float:
    d = abs(float(a) - float(b)) % 360.0
    return d if d <= 180.0 else 360.0 - d


def _rose_dir_deg(rose: dict | None) -> float | None:
    if not isinstance(rose, dict):
        return None
    ml = rose.get("most_likely")
    if isinstance(ml, dict) and isinstance(ml.get("dir_deg"), (int, float)):
        return float(ml["dir_deg"]) % 360.0
    best: tuple[float, float] | None = None
    for row in rose.get("directions_from") or []:
        if not isinstance(row, dict):
            continue
        pct, deg = row.get("pct"), row.get("dir_deg")
        if isinstance(pct, (int, float)) and isinstance(deg, (int, float)):
            if best is None or pct > best[0]:
                best = (float(pct), float(deg) % 360.0)
    return best[1] if best else None


def _rose_wind_kn(rose: dict | None) -> float | None:
    if not isinstance(rose, dict):
        return None
    for src in (rose.get("most_likely"), rose.get("vector_mean")):
        if isinstance(src, dict) and isinstance(src.get("speed_knots"), (int, float)):
            return float(src["speed_knots"])
    return None


def _in_cyclone_season(cyc: dict | None) -> bool | None:
    """True / False when the pearl says; None when the field is missing."""
    if not isinstance(cyc, dict):
        return None
    if cyc.get("in_season") is True:
        return True
    if cyc.get("in_season") is False:
        return False
    known = False
    for key in ("nearby", "tracks_in_month", "count", "cyclones"):
        val = cyc.get(key)
        if isinstance(val, (int, float)):
            known = True
            if val > 0:
                return True
    return False if known else None


def _pearl_climo(bag: dict) -> dict | None:
    """`climo` (plan) or `climatology` (perle riche) → rose + cyclone, or None."""
    raw = bag.get("climo") if isinstance(bag.get("climo"), dict) else None
    if raw is None and isinstance(bag.get("climatology"), dict):
        raw = bag["climatology"]
    if not raw:
        return None
    rose = raw.get("rose") if isinstance(raw.get("rose"), dict) else None
    if rose is None:
        point = raw.get("point") if isinstance(raw.get("point"), dict) else {}
        atlas = point.get("wind_atlas") if isinstance(point.get("wind_atlas"), dict) else None
        if atlas:
            rose = atlas
    cyc = raw.get("cyclones") if isinstance(raw.get("cyclones"), dict) else None
    if cyc is None and isinstance(raw.get("cyclone"), dict):
        cyc = raw["cyclone"]
    if cyc is None:
        point = raw.get("point") if isinstance(raw.get("point"), dict) else {}
        if isinstance(point.get("cyclone"), dict):
            cyc = point["cyclone"]
    if rose is None and cyc is None:
        return None
    return {"rose": rose, "cyclone": cyc, "month": raw.get("month")}


def _science_items(bag: dict) -> list[dict]:
    sci = bag.get("science")
    if isinstance(sci, dict):
        items = sci.get("nearby") or []
    elif isinstance(sci, list):
        items = sci
    else:
        items = []
    return [it for it in items if isinstance(it, dict) and it.get("name")]


def _project_items(bag: dict) -> list[dict]:
    rows = bag.get("projects") if isinstance(bag.get("projects"), list) else []
    return [p for p in rows if isinstance(p, dict) and p.get("name")]


def _gold_first(item: dict) -> tuple:
    gold = item.get("gold_on")
    rank = 0 if gold in (True, 1, "1", "true", "True") else 1
    nm = item.get("nm")
    dist = float(nm) if isinstance(nm, (int, float)) else 999.0
    return (rank, dist)


def _climo_title() -> dict:
    return {"fr": "Changement de régime", "en": "Regime change"}


def _sci_title() -> dict:
    return {"fr": "Station croisée", "en": "Station passed"}


def _pearl_event(pearl: dict, idx: int, kind: str, event: str, name: str | None, **extra) -> dict:
    out = {
        "kind": kind,
        "event": event,
        "lat": round(pearl["lat"], 4),
        "lon": round(pearl["lon"], 4),
        "sailNm": pearl["sailNm"],
        "idx": idx,
        "basis": "pearl",
        **extra,
    }
    if name:
        out["name"] = name
    return out


def _amp_dedup_keys(amp: dict, spoken: str = "") -> tuple[str, ...]:
    """siteId et préfixe de nom (« Lilleau-des-Niges » ×2) — AM1B."""
    keys: list[str] = []
    site = str(amp.get("siteId") or amp.get("site_id") or amp.get("id") or "").strip()
    if site:
        keys.append(f"id:{site.casefold()}")
    raw = spoken or str(amp.get("name") or "")
    prefix = _AMP_NAME_SPLIT.split(raw, maxsplit=1)[0].strip().casefold()
    if prefix:
        keys.append(f"name:{prefix}")
    return tuple(keys)


def _amp_is_export_fallback(amp: dict) -> bool:
    """Repli centroïde (source export, pas d'inside) : comportement d'avant."""
    src = str(amp.get("source") or "")
    if src == "export":
        return True
    if src == "polygon":
        return False
    return "inside" not in amp


def _amp_is_inside(amp: dict) -> bool:
    if _amp_is_export_fallback(amp):
        return False
    return bool(amp.get("inside"))


def _amp_keys_hit(keys: tuple[str, ...], pool: set[str]) -> bool:
    return bool(keys) and any(k in pool for k in keys)


def route_events_from_pearls(points: list[dict]) -> list[dict]:
    """What the warmed pearls know about the route, in order: ZEE entered /
    left, marine protected areas that come within reach (AMP réelles, RG3),
    projets Blue Intelligence (≤ PROJECT_NEAR_NM, gold_on d'abord), ports
    of entry passed (≤ POE_NEARBY_NM), coast milestones from WPI /
    capitaineries (≤ COAST_NEAR_NM), régime climatique (climo) and
    scientific stations (sci, ≤ SCI_NEARBY_NM, once per entity). Pearls
    not cached yet are unknown — no event is invented across a gap.

    Each event: { kind, event, name, mrgid | siteId | poeId | projectId,
    lat, lon, sailNm, idx, title, facts, entity }. The journal dates
    `sailNm`."""
    from ici_engine import (  # noqa: PLC0415
        is_fishing_amp, science_type_key, spoken_amp_name, thin_cache_get, thin_cache_key,
    )

    events: list[dict] = []
    state: dict | None = None      # confirmed ZEE (None = high seas)
    state_known = False
    candidate: tuple | None = None  # (zee_or_None, pearl, idx) seen once, waiting for a second pearl
    seen_amp: set[str] = set()
    inside_amp_rows: list[tuple[tuple[str, ...], dict, str]] = []
    seen_poe: set[str] = set()
    seen_sci: set[str] = set()
    seen_coast: set[str] = set()
    seen_project: set[str] = set()
    prev_climo: dict | None = None
    in_calms = False
    for idx, pearl in enumerate(sample_route_nm(points)):
        bag = thin_cache_get(thin_cache_key(pearl["lat"], pearl["lon"], 30.0))
        if bag is None:
            state_known = False
            candidate = None
            prev_climo = None
            in_calms = False
            inside_amp_rows = []
            continue
        zee = bag.get("zee") or None
        mrgid = zee.get("mrgid") if isinstance(zee, dict) else None
        ashore = bool(isinstance(zee, dict) and (zee.get("ashore") or str(zee.get("name", "")).startswith("À terre")))
        cur = None if (mrgid is None or ashore) else {"mrgid": mrgid, "name": zee.get("name"), "territory": zee.get("territory")}
        cur_id = cur["mrgid"] if cur else None
        state_id = state["mrgid"] if state else None
        # Ports of entry within reach of the pearl: once per port.
        for poe in (bag.get("poe") or [])[:3]:
            if not isinstance(poe, dict) or not poe.get("name"):
                continue
            nm = poe.get("nm")
            if not isinstance(nm, (int, float)) or nm > POE_NEARBY_NM:
                continue
            key = str(poe.get("id") or poe.get("site_id") or poe["name"])
            if key in seen_poe:
                continue
            seen_poe.add(key)
            events.append({
                "kind": "poe", "event": "passed", "name": poe["name"], "poeId": key,
                "nm": nm, "url": poe.get("url"), "mrgid": cur_id,
                "lat": round(pearl["lat"], 4), "lon": round(pearl["lon"], 4), "sailNm": pearl["sailNm"], "idx": idx, "basis": "pearl",
            })
        nearby = bag.get("nearby") if isinstance(bag.get("nearby"), dict) else {}
        for field in ("wpi", "capitaineries"):
            for item in nearby.get(field) or []:
                if not isinstance(item, dict) or not item.get("name"):
                    continue
                nm = item.get("nm")
                if not isinstance(nm, (int, float)) or nm > COAST_NEAR_NM:
                    continue
                name = str(item["name"]).strip()
                if not name or len(name) > 40 or "|" in name:
                    continue
                key = str(item.get("id") or item.get("site_id") or name)
                if key in seen_coast:
                    continue
                seen_coast.add(key)
                events.append({
                    "kind": "coast", "event": "passed", "name": name, "coastId": key,
                    "nm": nm, "mrgid": cur_id,
                    "lat": round(pearl["lat"], 4), "lon": round(pearl["lon"], 4),
                    "sailNm": pearl["sailNm"], "idx": idx, "basis": "pearl",
                })
        if not state_known:
            state, state_known, candidate = cur, True, None
        elif cur_id == state_id:
            candidate = None
        elif candidate is not None and (candidate[0]["mrgid"] if candidate[0] else None) == cur_id:
            # Two consecutive pearls agree (≥ 24 nm): a real crossing, not a
            # gazetteer flap along a boundary. Dated at the first of the two.
            first_pearl, first_idx = candidate[1], candidate[2]
            base = {"lat": round(first_pearl["lat"], 4), "lon": round(first_pearl["lon"], 4), "sailNm": first_pearl["sailNm"], "idx": first_idx, "basis": "pearl"}
            if state is not None:
                events.append({"kind": "zee", "event": "exit", "name": state["name"], "mrgid": state_id, "territory": state.get("territory"), **base})
            if cur is not None:
                events.append({"kind": "zee", "event": "enter", "name": cur["name"], "mrgid": cur_id, "territory": cur.get("territory"), **base})
            state, candidate = cur, None
        else:
            candidate = (cur, pearl, idx)
        amps = [
            a for a in (bag.get("amp") or [])
            if isinstance(a, dict) and a.get("name") and not is_fishing_amp(a)
        ]
        amps.sort(key=lambda a: (
            0 if a.get("inside") else 1,
            a.get("nm") if isinstance(a.get("nm"), (int, float)) else 999,
        ))
        current_inside: list[tuple[tuple[str, ...], dict, str]] = []
        for amp in amps:
            if not _amp_is_inside(amp):
                continue
            name = spoken_amp_name(amp["name"]) or str(amp["name"])
            keys = _amp_dedup_keys(amp, name)
            if keys:
                current_inside.append((keys, amp, name))
        current_keyset = {k for keys, _amp, _n in current_inside for k in keys}
        prev_keyset = {k for keys, _amp, _n in inside_amp_rows for k in keys}

        def _amp_row(event: str, amp: dict, name: str, keys: tuple[str, ...], *, nm: Any, inside: bool) -> dict:
            site = str(amp.get("siteId") or amp.get("site_id") or amp.get("id") or (keys[0] if keys else name))
            row = {
                "kind": "amp", "event": event, "name": name, "siteId": site,
                "nm": nm, "inside": inside,
                "visitUrl": amp.get("visitUrl") or amp.get("visit_url") or amp.get("url"),
                "lat": round(pearl["lat"], 4), "lon": round(pearl["lon"], 4),
                "sailNm": pearl["sailNm"], "idx": idx, "basis": "pearl",
            }
            src = amp.get("source")
            if src:
                row["source"] = src
            if amp.get("traffic"):
                row["traffic"] = amp.get("traffic")
            if amp.get("entry") is not None:
                row["entry"] = amp.get("entry")
            if amp.get("speed") is not None:
                row["speed"] = amp.get("speed")
            return row

        for keys, amp, name in inside_amp_rows:
            if _amp_keys_hit(keys, current_keyset):
                continue
            events.append(_amp_row("exit", amp, name, keys, nm=amp.get("nm") if isinstance(amp.get("nm"), (int, float)) else 0, inside=False))
        for keys, amp, name in current_inside:
            if _amp_keys_hit(keys, prev_keyset):
                continue
            events.append(_amp_row("enter", amp, name, keys, nm=0, inside=True))
            seen_amp.update(keys)
        inside_amp_rows = current_inside
        for amp in amps:
            if _amp_is_inside(amp):
                continue
            nm = amp.get("nm")
            if not isinstance(nm, (int, float)):
                continue
            limit = AMP_NEAR_NM if _amp_is_export_fallback(amp) else AMP_NEARBY_NM
            if nm > limit:
                continue
            name = spoken_amp_name(amp["name"]) or str(amp["name"])
            keys = _amp_dedup_keys(amp, name)
            if not keys or _amp_keys_hit(keys, seen_amp) or _amp_keys_hit(keys, current_keyset):
                continue
            seen_amp.update(keys)
            events.append(_amp_row("nearby", amp, name, keys, nm=nm, inside=False))
        projects = _project_items(bag)
        projects.sort(key=_gold_first)
        for proj in projects:
            nm = proj.get("nm")
            if not isinstance(nm, (int, float)) or nm > PROJECT_NEAR_NM:
                continue
            key = str(proj.get("id") or proj.get("site_id") or proj["name"])
            if key in seen_project:
                continue
            seen_project.add(key)
            events.append({
                "kind": "project", "event": "nearby", "name": str(proj["name"]).strip(),
                "projectId": key, "nm": nm,
                "gold_on": bool(proj.get("gold_on") in (True, 1, "1", "true", "True")),
                "url": proj.get("url"),
                "lat": round(pearl["lat"], 4), "lon": round(pearl["lon"], 4),
                "sailNm": pearl["sailNm"], "idx": idx, "basis": "pearl",
            })
        # Régime climatique (deux perles consécutives connues).
        climo = _pearl_climo(bag)
        if prev_climo is not None and climo is not None:
            prev_cyc, cur_cyc = _in_cyclone_season(prev_climo.get("cyclone")), _in_cyclone_season(climo.get("cyclone"))
            if prev_cyc is not None and cur_cyc is not None and prev_cyc != cur_cyc:
                ev = "cyclone-enter" if cur_cyc else "cyclone-exit"
                events.append(_pearl_event(
                    pearl, idx, "climo", ev, None,
                    title=_climo_title(),
                    facts={"inSeason": cur_cyc},
                    entity={"kind": "climo", "name": ev, "lat": round(pearl["lat"], 4), "lon": round(pearl["lon"], 4)},
                ))
            prev_wind, cur_wind = _rose_wind_kn(prev_climo.get("rose")), _rose_wind_kn(climo.get("rose"))
            calm_now = (
                prev_wind is not None and cur_wind is not None
                and prev_wind < CLIMO_CALM_KN and cur_wind < CLIMO_CALM_KN
            )
            if calm_now and not in_calms:
                mean = round((prev_wind + cur_wind) / 2.0, 1)
                events.append(_pearl_event(
                    pearl, idx, "climo", "calms", None,
                    title=_climo_title(),
                    facts={"windKn": mean},
                    entity={"kind": "climo", "name": "calms", "lat": round(pearl["lat"], 4), "lon": round(pearl["lon"], 4)},
                ))
            elif not calm_now:
                prev_dir, cur_dir = _rose_dir_deg(prev_climo.get("rose")), _rose_dir_deg(climo.get("rose"))
                if prev_dir is not None and cur_dir is not None:
                    delta = _angle_delta_deg(prev_dir, cur_dir)
                    if delta >= CLIMO_ROSE_TURN_DEG:
                        events.append(_pearl_event(
                            pearl, idx, "climo", "rose", None,
                            title=_climo_title(),
                            facts={
                                "fromDeg": round(prev_dir),
                                "toDeg": round(cur_dir),
                                "deltaDeg": round(delta),
                            },
                            entity={"kind": "climo", "name": "rose", "lat": round(pearl["lat"], 4), "lon": round(pearl["lon"], 4)},
                        ))
            in_calms = calm_now
        elif climo is None:
            in_calms = False
        prev_climo = climo
        # Station qualifiée à ≤ 10 nm, une fois par entité ; titre brut gardé pour la fiche.
        for item in _science_items(bag):
            if not science_type_key(item):
                continue
            nm = item.get("nm")
            if not isinstance(nm, (int, float)):
                ilat, ilon = item.get("lat"), item.get("lon")
                if isinstance(ilat, (int, float)) and isinstance(ilon, (int, float)):
                    nm = round(_haversine_nm(pearl["lat"], pearl["lon"], float(ilat), float(ilon)), 2)
                else:
                    continue
            if nm > SCI_NEARBY_NM:
                continue
            key = str(item.get("id") or item.get("site_id") or item.get("wmo") or item["name"])
            if key in seen_sci:
                continue
            seen_sci.add(key)
            slat = item.get("lat") if isinstance(item.get("lat"), (int, float)) else pearl["lat"]
            slon = item.get("lon") if isinstance(item.get("lon"), (int, float)) else pearl["lon"]
            events.append(_pearl_event(
                pearl, idx, "sci", "nearby", item["name"],
                siteId=key,
                nm=nm,
                url=item.get("url") or item.get("visit_url"),
                source=item.get("source"),
                sciKind=item.get("kind"),
                title=_sci_title(),
                facts={
                    "nm": round(float(nm), 1),
                    "name": item["name"],
                    "source": item.get("source"),
                    "kind": item.get("kind"),
                },
                entity={
                    "kind": "science",
                    "sciKind": item.get("kind"),
                    "name": item["name"],
                    "lat": round(float(slat), 4),
                    "lon": round(float(slon), 4),
                    "nm": nm,
                    "url": item.get("url") or item.get("visit_url"),
                    "source": item.get("source"),
                },
            ))
    return events


# ── store ───────────────────────────────────────────────────────────────────

def load_cache_from_disk() -> int:
    """Startup: migrate the former JSON cache into SQLite (once). The store
    itself needs no loading — the engine reads it on demand."""
    import pearl_store  # noqa: PLC0415
    return pearl_store.import_legacy_json(cache_path(), LEGACY_TTL_S)


# ── the warmer ────────────────────────────────────────────────────────────────

def _pearl_ready(key: str, rich: bool) -> bool:
    """Perle déjà en stock (et riche si demandé), sans décoder son sac : au boot, 3 272 json.loads
    tenaient la boucle d'événements ~2 min et l'API ne répondait plus (27 sept.)."""
    try:
        import pearl_store  # noqa: PLC0415
        from ici_engine import _fresh  # noqa: PLC0415
        meta = pearl_store.pearl_meta(key)
    except Exception:
        return False
    if not meta or not _fresh(meta):
        return False
    return (not rich) or meta.get("kind") == "rich"


def _drop_memory(key: str) -> None:
    """Oublie la perle en mémoire. La base garde l'ancienne jusqu'au recalcul réussi."""
    try:
        from ici_engine import _thin_cache  # noqa: PLC0415
        _thin_cache.pop(key, None)
    except Exception:
        pass


_AMP_REDO_NM = 6.0


async def warm_official_route(pause_s: float = WARM_PAUSE_S, rich: bool = True) -> dict[str, Any]:
    """Collect the (rich) pearl of every sample of the official route, gently.
    Pearls already rich in the store are skipped; thin ones are upgraded.
    A rich pearl whose AMP is still a centroid (or has no polygon mark) is redone."""
    from ici_engine import fill_dossier, thin_cache_get, thin_cache_key  # noqa: PLC0415
    from voyage_store import load_voyage  # noqa: PLC0415
    from voyage_clock import OFFICIAL_VOYAGE_ID  # noqa: PLC0415

    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    points = (voy or {}).get("points") or []
    pearls = sample_route(points)
    _state.update({
        "status": "running", "kind": "rich" if rich else "thin", "total": len(pearls),
        "done": 0, "cached": 0, "errors": 0, "startedAt": time.time(), "finishedAt": None,
        "stories": {"skipped": "on-demand"},
    })
    if not pearls:
        _state["status"] = "done"
        _state["finishedAt"] = time.time()
        _state["stories"] = {"skipped": "on-demand"}
        return status()
    month = None
    try:
        import httpx as _httpx  # noqa: PLC0415
        from ici_engine import refresh_amp_layer_sig  # noqa: PLC0415
        async with _httpx.AsyncClient(timeout=2.0) as _http:
            await refresh_amp_layer_sig(_http)
    except Exception:
        try:
            from ici_engine import load_amp_layer_sig  # noqa: PLC0415
            load_amp_layer_sig()
        except Exception:
            pass

    bad: list[tuple[str, float | None, float | None]] = []
    if rich:
        try:
            import pearl_store  # noqa: PLC0415
            bad = await asyncio.to_thread(pearl_store.non_polygon_amp_pearls, "rich")
        except Exception as exc:
            log.warning("perles AMP non polygones : %s", exc)
    bad_keys = {key for key, _lat, _lon in bad}

    def _near_bad(lat: float, lon: float) -> list[str]:
        found: list[str] = []
        for key, plat, plon in bad:
            if plat is None or plon is None:
                continue
            if _haversine_nm(lat, lon, plat, plon) <= _AMP_REDO_NM:
                found.append(key)
        return found

    _state["ampRedo"] = sum(
        1 for la, lo in pearls if thin_cache_key(la, lo, 30.0) in bad_keys or _near_bad(la, lo)
    )

    async def one(lat: float, lon: float) -> None:
        key = thin_cache_key(lat, lon, 30.0)
        near = _near_bad(lat, lon) if rich else []
        redo_this = bool(rich and (key in bad_keys or near))
        if redo_this:
            _drop_memory(key)
            for old in near:
                _drop_memory(old)
        elif _pearl_ready(key, rich) or thin_cache_get(key, rich=rich) is not None:
            _state["cached"] += 1
            _state["done"] += 1
            if _state["cached"] % 64 == 0:
                await asyncio.sleep(0)   # rendre la main à l'API entre deux paquets de perles déjà là
            return
        try:
            bag = await fill_dossier(
                lat, lon, 30.0, month=month, thin=True, rich=rich, force=redo_this,
            )
            if isinstance(bag, dict) and bag.get("ampFallback"):
                _state["errors"] += 1
            elif redo_this and thin_cache_get(key, rich=rich) is not None:
                import pearl_store  # noqa: PLC0415
                for old in near:
                    if old != key:
                        pearl_store.delete_pearl(old)
        except Exception as exc:  # network hiccup: keep going
            _state["errors"] += 1
            log.debug("perle %.3f,%.3f : %s", lat, lon, exc)
        _state["done"] += 1
        await asyncio.sleep(pause_s)

    # The local ZEE layer first: pearls filled with it never flap,
    # and the pearls already stored get their ZEE re-read right away.
    try:
        import zee_local  # noqa: PLC0415
        if await zee_local.ensure_loaded():
            _state["zeeRefreshed"] = await refresh_zee_local()
    except Exception as exc:
        log.debug("ZEE locale au démarrage du chauffeur : %s", exc)
    # Two pearls in flight: a rich pearl waits ~8 s on Overpass + EMODnet +
    # BI; two at a time halves the first run without leaning on Overpass.
    for i in range(0, len(pearls), WARM_PARALLEL):
        await asyncio.gather(*(one(la, lo) for la, lo in pearls[i:i + WARM_PARALLEL]))
    try:
        _state["zeeRefreshed"] = await refresh_zee_local()
    except Exception as exc:
        log.debug("relecture ZEE locale : %s", exc)
    # Plus de pré-génération de récits — le statut garde la clé stories.
    _state["stories"] = {"skipped": "on-demand"}
    if watch_enabled():
        try:
            import escale_watch  # noqa: PLC0415
            _state["watch"] = await escale_watch.run_daily(voy)
        except Exception as exc:
            log.debug("veille Tavily : %s", exc)
    # Journal des moments après les perles. RC18 (27 sept.) : quand le stock a son remplisseur
    # (processus séparé, avec l'horloge), l'API ne le refait pas — ici, sans horloge, ça produisait 770
    # moments sans date pour 46 s de CPU dans le processus de l'API.
    try:
        import official_store  # noqa: PLC0415
        external_filler = official_store.worker_enabled() and official_store.WORKER_MODE != "thread"
    except Exception:
        external_filler = False
    if not external_filler:
        try:
            from moment_journal import warm_moments  # noqa: PLC0415
            from voyage_clock import OFFICIAL_VOYAGE_ID  # noqa: PLC0415
            warmed = warm_moments(OFFICIAL_VOYAGE_ID)
            _state["moments"] = int((warmed or {}).get("count") or 0)
        except Exception as exc:
            log.debug("journal des moments : %s", exc)
    _state["status"] = "done"
    _state["finishedAt"] = time.time()
    log.info("perles officielles chauffées (%s) : %d (%d déjà en base, %d erreurs)",
             _state["kind"], _state["done"], _state["cached"], _state["errors"])
    return status()


async def refresh_zee_local(pause_s: float = 0.2) -> int:
    """Re-read the ZEE of every stored pearl with the local VLIZ layer:
    pearls filled from the gazetteer keep their rich layers, only `zee`
    (and the ports of entry, which hang on the ZEE) change. Returns the
    number of pearls corrected. No-op while the layer is not loaded."""
    import pearl_store  # noqa: PLC0415
    import zee_local  # noqa: PLC0415
    from ici_engine import _poe_from_fc, _get_json, bi_base, thin_cache_put, zee_from_record  # noqa: PLC0415

    if not zee_local.status()["loaded"]:
        return 0
    import httpx  # noqa: PLC0415
    changed = 0
    async with httpx.AsyncClient() as http:
        for n, (key, row) in enumerate(list(pearl_store.iter_pearls())):
            if n % 25 == 0:
                await asyncio.sleep(0)  # let the API breathe between batches
            bag = row["bag"]
            if (bag.get("sources") or {}).get("zee") == "vliz-local":
                continue
            try:
                lat, lon = float(key.split(":")[0]), float(key.split(":")[1])
            except Exception:
                continue
            local = zee_local.zee_at(lat, lon)
            if local is zee_local.UNKNOWN:
                return changed
            new_zee = local if local is not None else zee_from_record(None)
            old = bag.get("zee") or {}
            bag["sources"] = {**(bag.get("sources") or {}), "zee": "vliz-local"}
            if (old.get("mrgid") != new_zee.get("mrgid")) or bool(old.get("ashore")) != bool(new_zee.get("ashore")):
                bag["zee"] = {**new_zee, "gold": bool(old.get("gold")) if old.get("mrgid") == new_zee.get("mrgid") else False}
                mrgid = new_zee.get("mrgid")
                if mrgid:
                    try:
                        data = await _get_json(http, f"{bi_base()}/poe/ports?mrgid={int(mrgid)}", timeout=4.0)
                        bag["poe"] = _poe_from_fc(data, lat, lon)
                    except Exception:
                        bag["poe"] = []
                else:
                    bag["poe"] = []
                changed += 1
                await asyncio.sleep(pause_s)
            thin_cache_put(key, bag, row["kind"], lat, lon)
    if changed:
        log.info("ZEE locale : %d perles corrigées", changed)
    return changed


_pearls_cache: dict[str, Any] = {"rev": None, "pearls": None}


def official_pearls() -> dict[str, Any]:
    """The canonical pearls of the official route: the client samples the
    same positions, so its thin bags hit the warmed cache."""
    from voyage_store import load_voyage  # noqa: PLC0415
    from voyage_clock import OFFICIAL_VOYAGE_ID  # noqa: PLC0415

    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    points = (voy or {}).get("points") or []
    rev = (voy or {}).get("routeRev"), len(points)
    if _pearls_cache["pearls"] is None or _pearls_cache["rev"] != rev:
        _pearls_cache["pearls"] = [[round(la, 5), round(lo, 5)] for la, lo in sample_route(points)]
        _pearls_cache["rev"] = rev
    return {
        "voyageId": OFFICIAL_VOYAGE_ID if voy else None,
        "stepNm": SAMPLE_NM,
        "count": len(_pearls_cache["pearls"]),
        "pearls": _pearls_cache["pearls"],
        "warm": status(),
    }


def _watch_period_s(pause_s: float | None = None) -> float:
    if pause_s is not None:
        return float(pause_s)
    raw = (os.environ.get("NAVIGUIDE_TAVILY_WATCH_S") or "").strip()
    if not raw:
        return WATCH_LOOP_S
    try:
        return max(1.0, float(raw))
    except ValueError:
        return WATCH_LOOP_S


def start_background(loop: asyncio.AbstractEventLoop | None = None) -> bool:
    """Called at server startup. Never raises.

    La veille démarre même si le chauffeur de perles est coupé. Le retour
    « disabled » vient après ce démarrage.
    """
    try:
        load_cache_from_disk()
    except Exception as exc:
        log.warning("rechargement du cache perles : %s", exc)
    if watch_enabled():
        ensure_watch_loop(loop)
    if not warm_enabled():
        _state["status"] = "disabled"
        return False
    try:
        loop = loop or asyncio.get_event_loop()
        loop.create_task(warm_official_route())
        return True
    except Exception as exc:
        _state["status"] = "error"
        log.warning("chauffeur de perles non lancé : %s", exc)
        return False


_WATCH_LOOP_TASK: "asyncio.Task | None" = None
_WATCH_LOOP_RESTART = False


def ensure_watch_loop(loop=None) -> bool:
    """Lance la boucle de veille une seule fois (démarrage, ou interrupteur R42 allumé)."""
    global _WATCH_LOOP_TASK, _WATCH_LOOP_RESTART
    if _WATCH_LOOP_TASK is not None and not _WATCH_LOOP_TASK.done():
        if watch_enabled() and _WATCH_LOOP_TASK.cancelling():
            _WATCH_LOOP_RESTART = True
        return False
    try:
        loop = loop or asyncio.get_event_loop()
        _WATCH_LOOP_TASK = loop.create_task(_watch_loop())
        add_done = getattr(_WATCH_LOOP_TASK, "add_done_callback", None)
        if add_done is not None:
            add_done(_watch_loop_done)
        _state["watch"] = {"status": "scheduled"}
        return True
    except Exception as exc:
        log.warning("veille Tavily non lancée : %s", exc)
        return False


def cancel_watch_loop() -> bool:
    """Arrête la veille périodique dès que le réglage la désactive."""
    global _WATCH_LOOP_RESTART
    task = _WATCH_LOOP_TASK
    if task is None or task.done():
        return False
    _WATCH_LOOP_RESTART = False
    task.cancel()
    _state["watch"] = {"status": "disabled"}
    return True


def _watch_loop_done(task: asyncio.Task) -> None:
    """Libère la référence et honore un ON arrivé pendant l'annulation."""
    global _WATCH_LOOP_TASK, _WATCH_LOOP_RESTART
    if _WATCH_LOOP_TASK is task:
        _WATCH_LOOP_TASK = None
        restart = _WATCH_LOOP_RESTART
        _WATCH_LOOP_RESTART = False
        if restart and watch_enabled():
            ensure_watch_loop()


async def _watch_loop(pause_s: float | None = None) -> None:
    """Passe de veille seule : 2 min après le démarrage, puis toutes les 24 h.

    Une recherche par escale (`done:<slug>`), fenêtre J-10 → J+2.
    Pas d'enrichissement des perles (mémoire).
    """
    period = _watch_period_s(pause_s)
    await asyncio.sleep(120.0)
    while True:
        try:
            import escale_watch  # noqa: PLC0415
            _state["watch"] = await escale_watch.run_daily(enrich=False)
        except Exception as exc:
            log.debug("boucle veille : %s", exc)
        await asyncio.sleep(period)
