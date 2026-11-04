"""Journal serveur du voyage officiel — la mémoire du produit (plan général §1.2).

`voyage_data/official_journal/YYYY-MM-DD.json` : une liste d'entrées par jour
UTC, écrite par le serveur seul :

- `position`  : le bateau de l'horloge officielle à 00, 06, 12, 18 UTC
                (basis `clock` : la position planifiée, pas un GPS) ;
- `stop`      : arrivée / départ d'une escale franchie ;
- `grib`      : vent, pression, pluie, Hs au bateau à chaque cycle GRIB ingéré ;
- `note`      : mot du skipper / de l'équipe (admin, X-Naviguide-Admin) ;
- `zee`       : ZEE entrée / quittée, lue sur les perles chauffées de la route
                (basis `pearl`), datée par l'horloge — v2, 19 sept. ;
- `amp`       : aire marine protégée venue à portée d'une perle (basis `pearl`) ;
- `poe`       : port d'entrée officiel passé à ≤ 15 nm d'une perle (basis `pearl`) ;
- `wx`        : météo marquante au bateau, dérivée d'une entrée `grib` déjà
                journalisée (vent ≥ WX_GALE_KT ou mer WMO) — pas de GRIB,
                pas de `wx` (enrichi F2 : durée, max, level) ;
- `climo`     : changement de régime entre deux perles (rose ≥ 90°, calmes,
                saison cyclonique) — F2 ;
- `sci`       : station / campagne scientifique à ≤ 10 nm — F2 ;
- `news`      : veille Tavily d'une escale (J-10 → J+2), datée, avec URL
                — L4. Expire à J+2.

Rien n'est inventé : une position vient de l'horloge, un vent d'un GRIB
réellement téléchargé. Les trous restent des trous (`absent`), le journal
ne rebouche pas. Relu par GET /voyage/official/journal ; il nourrit ensuite
replay, chapitres de l'expédition, fiche d'escale « vécue ».
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from saildocs import wind_at_daily
from voyage_clock import parse_iso, sample_clock_at_time, to_iso
from voyage_store import voyage_dir

SLOT_HOURS = (0, 6, 12, 18)
BACKFILL_MAX_DAYS = 400          # toute l'expédition, jamais plus
TICK_MIN_S = 60.0                # les GET publics ne réécrivent pas plus souvent
NOTE_MAX_CHARS = 2000
KINDS = ("position", "stop", "grib", "note", "zee", "amp", "poe", "wx", "chat", "climo", "sci", "news")
CHAT_MAX_CHARS = 1200
WX_GALE_KT = 34.0          # Beaufort 8 « coup de vent »
WX_HS_ROUGH_M = 2.5        # WMO état de la mer 5 « forte »
WX_HS_VERY_ROUGH_M = 4.0   # WMO état de la mer 6 « très forte »
WX_HS_DURABLE_H = 6.0      # mer forte seulement si durable
WX_SLOT_H = 6.0            # durée d'un créneau GRIB isolé
WX_GAP_H = 9.0             # fusionner deux lectures remarquables plus proches
WX_HS_M = WX_HS_VERY_ROUGH_M  # nom historique : mer « très forte » instantanée

_LOCK = threading.RLock()
_last_tick = 0.0
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ── fichiers ────────────────────────────────────────────────────────────────

def journal_dir() -> Path:
    d = voyage_dir() / "official_journal"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _day_of(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _day_path(day: str) -> Path:
    if not _DAY_RE.match(day):
        raise ValueError("jour invalide")
    return journal_dir() / f"{day}.json"


def _read_day(day: str) -> List[dict]:
    path = _day_path(day)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _write_day(day: str, entries: List[dict]) -> None:
    path = _day_path(day)
    tmp = path.with_suffix(".tmp")
    entries = sorted(entries, key=lambda e: str(e.get("t") or ""))
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def _append(entries: Iterable[dict]) -> int:
    """Ajoute des entrées (dédoublonnées par id) dans le fichier de leur jour."""
    by_day: Dict[str, List[dict]] = {}
    for e in entries:
        by_day.setdefault(_day_of(parse_iso(e["t"])), []).append(e)
    added = 0
    with _LOCK:
        for day, news in by_day.items():
            current = _read_day(day)
            ids = {e.get("id") for e in current}
            fresh = [e for e in news if e.get("id") not in ids]
            if not fresh:
                continue
            _write_day(day, current + fresh)
            added += len(fresh)
    return added


def list_days() -> List[dict]:
    out = []
    for path in sorted(journal_dir().glob("????-??-??.json")):
        entries = _read_day(path.stem)
        kinds: Dict[str, int] = {}
        for e in entries:
            kinds[e.get("kind", "?")] = kinds.get(e.get("kind", "?"), 0) + 1
        out.append({"day": path.stem, "count": len(entries), "kinds": kinds})
    return out


def read_day(day: str) -> List[dict]:
    return _read_day(day)


def latest(limit: int = 50, kinds: Optional[Iterable[str]] = None) -> List[dict]:
    """Les `limit` dernières entrées, du plus récent au plus ancien."""
    wanted = set(kinds) if kinds else None
    out: List[dict] = []
    for path in sorted(journal_dir().glob("????-??-??.json"), reverse=True):
        day = _read_day(path.stem)
        day = [e for e in day if wanted is None or e.get("kind") in wanted]
        out.extend(reversed(day))
        if len(out) >= limit:
            break
    return out[:limit]


def entries_until(now, limit: Optional[int] = None, kinds: Optional[Iterable[str]] = None) -> List[dict]:
    """Every entry with t ≤ now, newest first. `limit` caps the list; it does not drop earlier days from the count when omitted."""
    if isinstance(now, datetime):
        now_dt = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    else:
        now_dt = parse_iso(str(now))
    now_dt = now_dt.astimezone(timezone.utc)
    wanted = set(kinds) if kinds else None
    cap = int(limit) if limit else None
    day_cut = now_dt.strftime("%Y-%m-%d")
    out: List[dict] = []
    for path in sorted(journal_dir().glob("????-??-??.json"), reverse=True):
        if path.stem > day_cut:
            continue
        kept: List[dict] = []
        for entry in _read_day(path.stem):
            if wanted is not None and entry.get("kind") not in wanted:
                continue
            raw = entry.get("t")
            if not raw:
                continue
            try:
                when = parse_iso(raw)
            except Exception:
                continue
            if when <= now_dt:
                kept.append(entry)
        out.extend(reversed(kept))
        if cap and len(out) >= cap:
            break
    return out[:cap] if cap else out


def _last_t(kind: str) -> Optional[datetime]:
    for path in sorted(journal_dir().glob("????-??-??.json"), reverse=True):
        ts = [e["t"] for e in _read_day(path.stem) if e.get("kind") == kind and e.get("t")]
        if ts:
            return parse_iso(max(ts))
    return None


def reset() -> None:
    global _last_tick
    with _LOCK:
        for path in journal_dir().glob("*.json"):
            path.unlink(missing_ok=True)
        _last_tick = 0.0


# ── positions ───────────────────────────────────────────────────────────────

def _slot_floor(t: datetime) -> datetime:
    t = t.astimezone(timezone.utc)
    h = max(s for s in SLOT_HOURS if s <= t.hour)
    return t.replace(hour=h, minute=0, second=0, microsecond=0)


def _slots_between(start: datetime, end: datetime) -> List[datetime]:
    """Créneaux 00/06/12/18 UTC dans ]start, end]."""
    out = []
    cur = _slot_floor(start) + timedelta(hours=6)
    while cur <= end:
        out.append(cur)
        cur += timedelta(hours=6)
    return out


def position_entry(clock: dict, slot: datetime) -> Optional[dict]:
    sample = sample_clock_at_time(clock, slot)
    if not sample or sample.get("lat") is None:
        return None
    return {
        "id": f"position:{to_iso(slot)}",
        "kind": "position",
        "t": to_iso(slot),
        "lat": round(float(sample["lat"]), 4),
        "lon": round(float(sample["lon"]), 4),
        "sailNm": round(float(sample.get("sailNm") or 0), 1),
        "filmNm": round(float(sample.get("filmNm") or 0), 1),
        "vehicle": sample.get("vehicle"),
        "status": sample.get("status"),
        "atQuay": bool(sample.get("atQuay")),
        "speedKnots": sample.get("speedKnots"),
        "basis": "clock",
    }


def record_positions(clock: dict, now: datetime, *, max_days: int = BACKFILL_MAX_DAYS) -> int:
    t0 = parse_iso(clock["t0"])
    start = _last_t("position") or (t0 - timedelta(hours=6))
    floor = now - timedelta(days=max_days)
    if start < floor:
        start = floor
    if start < t0 - timedelta(hours=6):
        start = t0 - timedelta(hours=6)
    entries = [e for e in (position_entry(clock, s) for s in _slots_between(start, now)) if e]
    return _append(entries)


# ── escales ─────────────────────────────────────────────────────────────────

def _days_at_quay(hold_hours: Any) -> Optional[int]:
    if not isinstance(hold_hours, (int, float)) or hold_hours <= 0:
        return None
    return int(round(float(hold_hours) / 24.0))


def _stop_latlon(clock: dict, mark: dict, when: datetime) -> tuple[Optional[float], Optional[float]]:
    if isinstance(mark.get("lat"), (int, float)) and isinstance(mark.get("lon"), (int, float)):
        return float(mark["lat"]), float(mark["lon"])
    sample = sample_clock_at_time(clock, when)
    if sample and isinstance(sample.get("lat"), (int, float)) and isinstance(sample.get("lon"), (int, float)):
        return float(sample["lat"]), float(sample["lon"])
    return None, None


def _stop_entry(clock: dict, mark: dict, when: datetime, event: str, key: str) -> dict:
    name = str(mark.get("name") or "").strip()
    lat, lon = _stop_latlon(clock, mark, when)
    hold = mark.get("holdHours") if event == "arrival" else None
    days = _days_at_quay(hold) if event == "arrival" else None
    sights: List[dict] = []
    if event == "arrival" and lat is not None and lon is not None:
        try:
            from escale_api import tourism_highlights_from_cache  # noqa: PLC0415
            sights = tourism_highlights_from_cache(name, lat, lon)
        except Exception:
            sights = []
    facts: Dict[str, Any] = {}
    if days is not None:
        facts["daysAtQuay"] = days
    if sights:
        facts["sights"] = [s["name"] for s in sights]
    entry: Dict[str, Any] = {
        "id": f"stop:{key}:{event}",
        "kind": "stop",
        "t": to_iso(when),
        "event": event,
        "name": name,
        "filmNm": mark.get("filmNm"),
        "title": {"fr": "Escale", "en": "Stopover"},
        "basis": "clock",
    }
    if hold is not None:
        entry["holdHours"] = hold
    if days is not None:
        entry["daysAtQuay"] = days
    if sights:
        entry["sights"] = [s["name"] for s in sights]
    if facts:
        entry["facts"] = facts
    if lat is not None and lon is not None:
        entry["lat"] = round(lat, 4)
        entry["lon"] = round(lon, 4)
        entry["entity"] = {
            "kind": "escale",
            "name": name,
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "url": sights[0].get("url") if sights else None,
        }
    return entry


def record_stops(clock: dict, now: datetime) -> int:
    t0 = parse_iso(clock["t0"])
    entries = []
    for m in clock.get("marks") or []:
        name = str(m.get("name") or "").strip()
        if not name or m.get("tHours") is None:
            continue
        arrival = t0 + timedelta(hours=float(m["tHours"]))
        key = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if arrival <= now:
            entries.append(_stop_entry(clock, m, arrival, "arrival", key))
        hold = float(m.get("holdHours") or 0)
        departure = arrival + timedelta(hours=hold)
        if hold > 0 and departure <= now:
            entries.append(_stop_entry(clock, m, departure, "departure", key))
    return _append(entries)


# ── événements de route (perles) ────────────────────────────────────────────

def _time_at_sail_nm(clock: dict, sail_nm: float) -> Optional[datetime]:
    """When the official clock puts the boat at `sail_nm` sea miles (first crossing)."""
    verts = clock.get("vertices") or []
    t0 = parse_iso(clock["t0"])
    x = float(sail_nm)
    for a, b in zip(verts, verts[1:]):
        sa, sb = float(a.get("sailNm") or 0), float(b.get("sailNm") or 0)
        if sb < x - 1e-6 or sb <= sa:
            continue
        if x < sa - 1e-6:
            return t0 + timedelta(hours=float(a["tHours"]))
        t = (x - sa) / (sb - sa) if sb > sa else 0.0
        hours = float(a["tHours"]) + t * (float(b["tHours"]) - float(a["tHours"]))
        return t0 + timedelta(hours=hours)
    return None


def record_route_events(voy: Optional[dict], clock: Optional[dict], now: datetime) -> int:
    """ZEE crossings and MPA neighbourhoods read on the warmed pearls, dated
    by the clock, once each (idempotent ids). Pearls not warmed yet: nothing
    is written — the next tick will, when the cache knows them."""
    if not voy or not clock or not voy.get("points"):
        return 0
    from ici_warm import route_events_from_pearls  # noqa: PLC0415
    entries = []
    for ev in route_events_from_pearls(voy["points"]):
        when = _time_at_sail_nm(clock, ev["sailNm"])
        if when is None or when > now:
            continue
        if ev["kind"] == "poe":
            ident = ev.get("poeId")
        elif ev["kind"] == "sci":
            ident = ev.get("siteId") or ev.get("name")
        elif ev["kind"] == "climo":
            ident = ev.get("event") or "regime"
        else:
            ident = ev.get("mrgid") or ev.get("siteId") or ev.get("name") or ""
        key = re.sub(r"[^a-z0-9]+", "-", str(ident).lower()).strip("-")
        entries.append({
            "id": f"{ev['kind']}:{ev['event']}:{key}:{ev['idx']}",
            "t": to_iso(when),
            **{k: v for k, v in ev.items() if k != "idx"},
        })
    # Pearl-derived lines are a *reading* of the pearls, not a record: as the
    # warmer refines them (thin → rich, a better ZEE, a better date), the
    # reading changes. Keep the journal equal to the current reading — never
    # a pile of readings. A same id with another time is a new reading too.
    _drop_basis_not_in("pearl", {(e["id"], e["t"]) for e in entries})
    return _append(entries)


def _drop_basis_not_in(basis: str, keep: set) -> int:
    """Remove entries of `basis` whose (id, t) is not in `keep`."""
    removed = 0
    with _LOCK:
        for path in sorted(journal_dir().glob("*.json")):
            entries = _read_day(path.stem)
            kept = [e for e in entries if e.get("basis") != basis or (e.get("id"), e.get("t")) in keep]
            if len(kept) != len(entries):
                removed += len(entries) - len(kept)
                if kept:
                    _write_day(path.stem, kept)
                else:
                    try:
                        path.unlink()
                    except OSError:
                        pass
    return removed


def _wx_hours(value: Optional[float]) -> Optional[float]:
    if not isinstance(value, (int, float)):
        return None
    hours = float(value)
    return int(hours) if hours == int(hours) else round(hours, 1)


def _wx_level(max_hs: Optional[float]) -> Optional[str]:
    if not isinstance(max_hs, (int, float)):
        return None
    if max_hs >= WX_HS_VERY_ROUGH_M:
        return "très forte"
    if max_hs >= WX_HS_ROUGH_M:
        return "forte"
    return None


def _wx_title(event: str, level: Optional[str]) -> dict:
    if event == "sea":
        if level == "très forte":
            return {"fr": "Mer très forte", "en": "Very rough sea"}
        return {"fr": "Mer forte", "en": "Rough sea"}
    return {"fr": "Coup de vent", "en": "Gale"}


def wx_entry_from_grib(
    grib: dict,
    *,
    hours: Optional[float] = None,
    max_wind: Optional[float] = None,
    max_hs: Optional[float] = None,
) -> Optional[dict]:
    """A `wx` line derived from a journaled GRIB reading — or None when the
    weather was unremarkable. Same numbers, same time, nothing added.
    Durée (heures), max, level WMO (forte / très forte)."""
    wind = grib.get("windKnots")
    hs = grib.get("hs")
    dur = hours if isinstance(hours, (int, float)) else WX_SLOT_H
    peak_wind = max_wind if isinstance(max_wind, (int, float)) else (wind if isinstance(wind, (int, float)) else None)
    peak_hs = max_hs if isinstance(max_hs, (int, float)) else (hs if isinstance(hs, (int, float)) else None)
    gale = isinstance(peak_wind, (int, float)) and peak_wind >= WX_GALE_KT
    very = isinstance(peak_hs, (int, float)) and peak_hs >= WX_HS_VERY_ROUGH_M
    rough = isinstance(peak_hs, (int, float)) and peak_hs >= WX_HS_ROUGH_M and dur >= WX_HS_DURABLE_H
    if not gale and not very and not rough:
        return None
    event = "gale" if gale else "sea"
    level = _wx_level(peak_hs)
    hours_out = _wx_hours(dur)
    facts: Dict[str, Any] = {}
    if isinstance(wind, (int, float)):
        facts["windKnots"] = wind
    if isinstance(peak_wind, (int, float)):
        facts["maxWindKnots"] = peak_wind
    if isinstance(hs, (int, float)):
        facts["hs"] = hs
    if isinstance(peak_hs, (int, float)):
        facts["maxHs"] = peak_hs
    if hours_out is not None:
        facts["hours"] = hours_out
    if level:
        facts["level"] = level
    entry: Dict[str, Any] = {
        "id": f"wx:{grib.get('id') or grib.get('cycle') or grib.get('t')}",
        "kind": "wx",
        "t": grib["t"],
        "event": event,
        "windKnots": wind,
        "dirFromDeg": grib.get("dirFromDeg"),
        "hs": hs,
        "hours": hours_out,
        "maxWindKnots": peak_wind,
        "maxHs": peak_hs,
        "level": level,
        "title": _wx_title(event, level),
        "facts": facts,
        "lat": grib.get("lat"),
        "lon": grib.get("lon"),
        "model": grib.get("model"),
        "from": grib.get("id"),
        "basis": grib.get("basis") or "forecast",
    }
    if isinstance(grib.get("lat"), (int, float)) and isinstance(grib.get("lon"), (int, float)):
        entry["entity"] = {
            "kind": "wx",
            "name": event,
            "lat": grib.get("lat"),
            "lon": grib.get("lon"),
        }
    return {k: v for k, v in entry.items() if v is not None}


def _grib_time(grib: dict) -> Optional[datetime]:
    try:
        return parse_iso(grib["t"]) if grib.get("t") else None
    except Exception:
        return None


def _wx_runs(gribs: Iterable[dict]) -> List[dict]:
    timed: List[tuple[datetime, dict]] = []
    for g in gribs:
        t = _grib_time(g)
        if t is not None:
            timed.append((t, g))
    timed.sort(key=lambda x: x[0])
    runs: List[dict] = []
    cur: Optional[dict] = None
    for t, g in timed:
        wind, hs = g.get("windKnots"), g.get("hs")
        active = (
            (isinstance(wind, (int, float)) and wind >= WX_GALE_KT)
            or (isinstance(hs, (int, float)) and hs >= WX_HS_ROUGH_M)
        )
        if not active:
            cur = None
            continue
        if cur is not None and (t - cur["tLast"]).total_seconds() / 3600.0 <= WX_GAP_H:
            cur["tLast"] = t
            cur["gribs"].append(g)
        else:
            cur = {"tFirst": t, "tLast": t, "gribs": [g]}
            runs.append(cur)
    out: List[dict] = []
    for run in runs:
        span_h = (run["tLast"] - run["tFirst"]).total_seconds() / 3600.0
        hours = max(WX_SLOT_H, span_h)
        winds = [g["windKnots"] for g in run["gribs"] if isinstance(g.get("windKnots"), (int, float))]
        seas = [g["hs"] for g in run["gribs"] if isinstance(g.get("hs"), (int, float))]
        out.append({
            "hours": hours,
            "maxWind": max(winds) if winds else None,
            "maxHs": max(seas) if seas else None,
            "gribs": run["gribs"],
        })
    return out


def wx_events_from_gribs(gribs: Iterable[dict]) -> List[dict]:
    """Une entrée `wx` par épisode (run de GRIBs remarquables), avec durée et max."""
    events: List[dict] = []
    for run in _wx_runs(gribs):
        first = run["gribs"][0]
        entry = wx_entry_from_grib(
            first, hours=run["hours"], max_wind=run["maxWind"], max_hs=run["maxHs"],
        )
        if entry:
            events.append(entry)
    return events


def record_wx(now: datetime) -> int:
    """Derive `wx` entries from every journaled GRIB reading (idempotent)."""
    del now
    return _append(wx_events_from_gribs(latest(5000, kinds=("grib",))))


def _samples_from_hindcast_clock(clock: dict, now: datetime) -> List[dict]:
    """Sommets hindcast déjà intégrés — durée et max viennent des heures réelles."""
    out = []
    t0 = parse_iso(clock["t0"])
    for v in clock.get("vertices") or []:
        if (v.get("regime") or v.get("kind")) != "hindcast":
            continue
        try:
            when = parse_iso(v["iso"]) if v.get("iso") else t0 + timedelta(hours=float(v.get("tHours") or 0))
        except Exception:
            continue
        if when > now:
            continue
        out.append({
            "id": f"hindcast:{v.get('iso') or v.get('tHours')}",
            "t": v.get("iso") or to_iso(when),
            "windKnots": v.get("windKnots"),
            "dirFromDeg": v.get("dirFromDeg"),
            "hs": v.get("hs"),
            "lat": v.get("lat"),
            "lon": v.get("lon"),
            "model": "hindcast",
            "basis": "hindcast",
        })
    return out


def record_wx_from_hindcast(clock: Optional[dict], now: datetime) -> int:
    """wx depuis l'horloge hindcast : durée et max, basis hindcast."""
    if not clock:
        return 0
    events = wx_events_from_gribs(_samples_from_hindcast_clock(clock, now))
    for e in events:
        e["basis"] = "hindcast"
        e["from"] = e.get("from") or e.get("id")
        if e.get("id") and not str(e["id"]).startswith("wx:hindcast"):
            e["id"] = f"wx:hindcast:{e.get('t')}"
    return _append(events)


# ── GRIB ────────────────────────────────────────────────────────────────────

def record_grib(record: Optional[dict], clock: Optional[dict], now: datetime) -> bool:
    """Le GRIB du cycle au bateau (position horloge à `now`). Une entrée par cycle."""
    if not record or record.get("status") != "ready" or not clock:
        return False
    sample = sample_clock_at_time(clock, now)
    if not sample or sample.get("lat") is None:
        return False
    lat, lon = float(sample["lat"]), float(sample["lon"])
    wind = wind_at_daily(record, lat, lon, now)
    if not wind:
        return False
    cycle = str(record.get("cycle") or record.get("issued") or to_iso(now))
    entry = {
        "id": f"grib:{cycle}",
        "kind": "grib",
        "t": to_iso(now),
        "cycle": cycle,
        "lat": round(lat, 4),
        "lon": round(lon, 4),
        "windKnots": wind.get("windKnots"),
        "dirFromDeg": wind.get("dirFromDeg"),
        "pressHpa": wind.get("pressHpa"),
        "rainMm": wind.get("rainMm"),
        "hs": wind.get("hs"),
        "model": wind.get("model"),
        "waveModel": wind.get("waveModel"),
        "source": record.get("source"),
        "basis": "forecast",
    }
    added = _append([entry]) > 0
    if added:
        wx = wx_entry_from_grib(entry)
        if wx:
            _append([wx])
    return added


# ── notes ───────────────────────────────────────────────────────────────────

def add_note(text: str, now: datetime, *, author: str = "skipper", lang: str = "fr") -> dict:
    clean = " ".join(str(text or "").split())
    if not clean:
        raise ValueError("note vide")
    if len(clean) > NOTE_MAX_CHARS:
        raise ValueError(f"note trop longue (> {NOTE_MAX_CHARS} caractères)")
    entry = {
        "id": f"note:{uuid.uuid4().hex[:12]}",
        "kind": "note",
        "t": to_iso(now),
        "text": clean,
        "author": (author or "skipper")[:40],
        "lang": (lang or "fr")[:5],
        "basis": "human",
    }
    _append([entry])
    return entry


def add_chat(question: str, answer: str, summary: str, now: datetime, *, lang: str = "fr", engine: str | None = None) -> dict:
    """Un échange avec le journal de bord : horodatage, question,
    réponse, résumé. Écrit tel quel — le LLM a répondu, le journal se souvient."""
    q = " ".join(str(question or "").split())[:CHAT_MAX_CHARS]
    a = " ".join(str(answer or "").split())[:CHAT_MAX_CHARS]
    if not q or not a:
        raise ValueError("échange vide")
    entry = {
        "id": f"chat:{uuid.uuid4().hex[:12]}",
        "kind": "chat",
        "t": to_iso(now),
        "question": q,
        "answer": a,
        "summary": " ".join(str(summary or "").split())[:300] or q[:120],
        "lang": (lang or "fr")[:5],
        "engine": (engine or None),
        "basis": "human+llm",
    }
    _append([entry])
    return entry


# ── veille ─────────────────────────────────────────────────────────

def record_news(entry: dict) -> bool:
    """Une entrée `news` datée, avec URL. Idempotente (id = news:slug:jour)."""
    if not isinstance(entry, dict) or entry.get("kind") != "news":
        return False
    if not entry.get("id") or not entry.get("t") or not entry.get("text"):
        return False
    return _append([entry]) > 0


# ── tick ────────────────────────────────────────────────────────────────────

def tick(voy: Optional[dict], now: datetime, *, force: bool = False) -> Dict[str, Any]:
    """Positions et escales manquantes depuis la dernière fois. Peu coûteux,
    borné à une écriture par minute (les GET publics l'appellent)."""
    global _last_tick
    if not voy or not voy.get("clock"):
        return {"positions": 0, "stops": 0, "skipped": True}
    mono = time.monotonic()
    with _LOCK:
        if not force and mono - _last_tick < TICK_MIN_S:
            return {"positions": 0, "stops": 0, "skipped": True}
        _last_tick = mono
    clock = voy["clock"]
    out = {
        "positions": record_positions(clock, now),
        "stops": record_stops(clock, now),
        "skipped": False,
    }
    try:
        out["routeEvents"] = record_route_events(voy, clock, now)
    except Exception:  # the pearls never break the journal
        out["routeEvents"] = 0
    try:
        out["wx"] = record_wx(now)
    except Exception:
        out["wx"] = 0
    try:
        out["wxHindcast"] = record_wx_from_hindcast(clock, now)
    except Exception:
        out["wxHindcast"] = 0
    return out


EVENT_KINDS = ("stop", "grib", "note", "zee", "amp", "poe", "wx", "chat", "climo", "sci", "news")
EVENTS_MAX = 800


def summary(limit: int = 50) -> Dict[str, Any]:
    days = list_days()
    return {
        "days": days,
        "count": sum(d["count"] for d in days),
        "first": days[0]["day"] if days else None,
        "last": days[-1]["day"] if days else None,
        "latest": latest(limit),
        # Everything but the 4-a-day positions, whole voyage: what the story
        # of the crossing reads (ZEE crossed, MPA met, stops, wind, notes).
        "events": latest(EVENTS_MAX, kinds=EVENT_KINDS),
        "kinds": list(KINDS),
    }
