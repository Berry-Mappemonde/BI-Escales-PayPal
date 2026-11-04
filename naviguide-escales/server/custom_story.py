"""Moments et film d'un voyage perso — à la demande.

Contrat DM8A :
  moments_for_voyage(voyage, *, budget_nm=2000) →
    {status, moments, coverageNm, totalNm, fingerprint, computedAt, skipped}

Contrat DM8B (DM8C consomme sans adaptation) :
  film_for_voyage(voyage, moments, lang, seconds, style) →
    même forme que GET /voyage/official/film
    (status, lang, seconds, style, chapters[], anchors[], text, sentences,
     hasWritten: false, source: "rules", chars, targetSeconds, estimatedSeconds)

- film : cache kv namespace ``custom-film``, clé = empreinte des moments
  + FILM_SCRIPT_REV + lang + seconds + style, TTL 7 jours ;
- status preparing tant que les moments DM8A ne sont pas ready ;
- aucun LLM (style=written rend le brut, hasWritten false) ;
- le stock officiel n'est ni lu ni écrit.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from ici_warm import SAMPLE_NM, sample_route_nm

log = logging.getLogger("naviguide-simulator.custom-story")

NS = "custom-moments"
FILM_NS = "custom-film"
TTL_S = 7 * 86400.0
DEFAULT_BUDGET_NM = 2000.0
RADIUS_NM = 30.0
# Un sac riche froid coûte 1–8 s : sans borne de temps, GET /moments tenait
# plusieurs minutes (La Rochelle → Horta, 55 perles). Reprise au poll suivant.
MAX_CHUNK_S = float(os.environ.get("NAVIGUIDE_CUSTOM_MOMENTS_CHUNK_S") or 12.0)

_COMPUTE_LOCK = threading.Lock()
_FILM_LOCK = threading.Lock()
_FILM_BUILDS = 0


def _now_iso() -> str:
    from voyage_clock import to_iso  # noqa: PLC0415
    return to_iso(datetime.now(timezone.utc))


def _ici_rev() -> str:
    try:
        from official_store import ICI_REV, MOMENTS_REV  # noqa: PLC0415
        return f"{ICI_REV}:{MOMENTS_REV}"
    except Exception:
        try:
            from ici_engine import PEARL_REV  # noqa: PLC0415
            return str(PEARL_REV)
        except Exception:
            return "rg3"


def _speed_factor() -> float:
    try:
        from voyage_clock import polar_efficiency  # noqa: PLC0415
        return round(float(polar_efficiency()), 4)
    except Exception:
        return 1.0


def voyage_fingerprint(voyage: dict) -> str:
    """sha1 court de (points 1e-4, t0, polaire / facteur de vitesse, ICI_REV)."""
    points: list[list[float]] = []
    for p in voyage.get("points") or []:
        if not isinstance(p, dict):
            continue
        try:
            points.append([round(float(p["lat"]), 4), round(float(p["lon"]), 4)])
        except (KeyError, TypeError, ValueError):
            continue
    marks: list[list] = []
    for m in voyage.get("marks") or []:
        if not isinstance(m, dict):
            continue
        try:
            nm = m.get("nm")
            if nm is None:
                nm = m.get("filmNm") or 0
            marks.append([str(m.get("name") or ""), round(float(nm), 1)])
        except (TypeError, ValueError):
            continue
    blob = json.dumps(
        {
            "points": points,
            "marks": marks,
            "t0": str(voyage.get("t0") or ""),
            "polar": str(voyage.get("expedition_id") or ""),
            "speedFactor": _speed_factor(),
            "startAt": str(voyage.get("startAt") or ""),
            "iciRev": _ici_rev(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def _pointer_key(voyage_id: str) -> str:
    return f"id:{voyage_id}"


def drop_cached_moments(voyage_id: str) -> None:
    """Supprime l'entrée custom-moments d'un voyage purgé. Jamais d'exception."""
    if not voyage_id:
        return
    try:
        import pearl_store  # noqa: PLC0415
        hit = pearl_store.kv_get(NS, _pointer_key(voyage_id))
        fp = None
        if hit:
            val = hit.get("value")
            if isinstance(val, str):
                fp = val
            elif isinstance(val, dict):
                fp = val.get("fingerprint")
        pearl_store.kv_delete(NS, _pointer_key(voyage_id))
        if fp:
            pearl_store.kv_delete(NS, fp)
    except Exception as exc:
        log.warning("purge custom-moments %s : %s", voyage_id, exc)
    drop_cached_film(voyage_id)


def _load_entry(fp: str) -> Optional[dict]:
    import pearl_store  # noqa: PLC0415
    hit = pearl_store.kv_get(NS, fp, max_age_s=TTL_S)
    if not hit:
        return None
    val = hit.get("value")
    return val if isinstance(val, dict) else None


def _save_entry(fp: str, voyage_id: str | None, entry: dict) -> None:
    import pearl_store  # noqa: PLC0415
    pearl_store.kv_put(NS, fp, entry)
    if voyage_id:
        pearl_store.kv_put(NS, _pointer_key(voyage_id), fp)


def _public(entry: dict) -> dict:
    return {
        "status": entry.get("status") or "preparing",
        "moments": list(entry.get("moments") or []),
        "coverageNm": float(entry.get("coverageNm") or 0),
        "totalNm": float(entry.get("totalNm") or 0),
        "fingerprint": str(entry.get("fingerprint") or ""),
        "computedAt": entry.get("computedAt") or _now_iso(),
        "skipped": int(entry.get("skipped") or 0),
        **({"voyageId": entry["voyageId"]} if entry.get("voyageId") else {}),
    }


def preparing_payload(voyage: dict | None = None, *, fingerprint: str = "",
                      reason: str | None = None) -> dict:
    vid = (voyage or {}).get("voyageId")
    out = {
        "status": "preparing",
        "moments": [],
        "coverageNm": 0.0,
        "totalNm": 0.0,
        "fingerprint": fingerprint or (voyage_fingerprint(voyage) if voyage else ""),
        "computedAt": _now_iso(),
        "skipped": 0,
    }
    if vid:
        out["voyageId"] = vid
    if reason:
        out["reason"] = str(reason)
    return out


def _clock_for(voyage: dict) -> Optional[dict]:
    clock = voyage.get("clock") if isinstance(voyage.get("clock"), dict) else None
    if clock and (clock.get("vertices") or []):
        return clock
    t0 = voyage.get("t0")
    if not t0:
        return None
    try:
        from voyage_clock import build_voyage_clock  # noqa: PLC0415
    except Exception:
        return None
    polar_raw = None
    try:
        from polar_api import _load_polar_data  # noqa: PLC0415
        polar = _load_polar_data(voyage.get("expedition_id") or "")
        polar_raw = {
            "twa_rows": list(polar.twa_rows),
            "tws_cols": list(polar.tws_cols),
            "matrix": polar.matrix.tolist(),
        }
    except Exception:
        polar_raw = None
    try:
        return build_voyage_clock(
            voyage.get("points") or [],
            voyage.get("marks") or [],
            t0,
            polar_raw=polar_raw,
            start_at=voyage.get("startAt") or "la-rochelle",
            wind_fn=None,
        )
    except Exception as exc:
        log.warning("horloge perso : %s", exc)
        return None


def _bag_key(lat: float, lon: float) -> str:
    from ici_engine import thin_cache_key  # noqa: PLC0415
    return thin_cache_key(lat, lon, RADIUS_NM)


def _resolve_bag(
    lat: float,
    lon: float,
    bag_fn: Optional[Callable[[float, float], Any]],
    skipped_keys: set[str],
) -> tuple[Optional[dict], bool]:
    """(bag | None, called_fill). None = sauter la perle."""
    from ici_engine import thin_cache_get, thin_cache_put  # noqa: PLC0415

    key = _bag_key(lat, lon)
    if key in skipped_keys:
        return None, False
    cached = thin_cache_get(key)
    if cached is not None:
        return cached, False
    try:
        if bag_fn is not None:
            bag = bag_fn(lat, lon)
        else:
            from ici_warm import get_pearl_bag  # noqa: PLC0415
            bag = get_pearl_bag(lat, lon)
    except Exception as exc:
        log.debug("sac /ici perso %.4f,%.4f : %s", lat, lon, exc)
        skipped_keys.add(key)
        return None, True
    if not isinstance(bag, dict):
        skipped_keys.add(key)
        return None, True
    try:
        thin_cache_put(key, bag, "thin", lat, lon)
    except Exception:
        pass
    return bag, True


def _advance(
    voyage: dict,
    samples: list[dict],
    entry: dict,
    *,
    budget_nm: float,
    bag_fn: Optional[Callable[[float, float], Any]],
) -> dict:
    from moment_journal import rows_from_voyage  # noqa: PLC0415

    total_nm = float(samples[-1]["sailNm"]) if samples else 0.0
    done = int(entry.get("done") or 0)
    skipped_keys = set(entry.get("skippedKeys") or [])
    skipped = int(entry.get("skipped") or 0)

    if done >= len(samples):
        entry["status"] = "ready"
        entry["coverageNm"] = total_nm
        entry["totalNm"] = total_nm
        entry["computedAt"] = _now_iso()
        return entry

    budget = float(budget_nm) if budget_nm and budget_nm > 0 else SAMPLE_NM
    base_nm = float(samples[done].get("sailNm") or 0)
    limit_nm = base_nm + budget
    chunk_s = float(MAX_CHUNK_S) if MAX_CHUNK_S and MAX_CHUNK_S > 0 else 1e9
    deadline = time.monotonic() + chunk_s

    def _pearl(sample: dict) -> Optional[dict]:
        try:
            lat, lon = float(sample["lat"]), float(sample["lon"])
        except (KeyError, TypeError, ValueError):
            return None
        bag, _called = _resolve_bag(lat, lon, bag_fn, skipped_keys)
        if bag is None:
            return None
        pearl = dict(bag)
        pearl.setdefault("lat", lat)
        pearl.setdefault("lon", lon)
        pearl.setdefault("sailNm", sample.get("sailNm"))
        pearl.setdefault("at", {"lat": lat, "lon": lon})
        return pearl

    bags: list[dict] = []
    # Reprise : les perles déjà vues sont dans le cache perles ; on les relit
    # pour reconstruire les diffs, sans rappeler le sac.
    for sample in samples[:done]:
        pearl = _pearl(sample)
        if pearl is not None:
            bags.append(pearl)

    end = done
    while end < len(samples):
        sample = samples[end]
        sail = float(sample.get("sailNm") or 0)
        if end > done and sail > limit_nm:
            break
        if end > done and time.monotonic() >= deadline:
            break
        pearl = _pearl(sample)
        if pearl is None:
            skipped += 1
        else:
            bags.append(pearl)
        end += 1

    clock = _clock_for(voyage) or {}
    voy = {
        **voyage,
        "clock": clock,
        "pearls": bags,
    }
    vid = str(voyage.get("voyageId") or "custom")
    try:
        rows = rows_from_voyage(vid, voy)
    except Exception as exc:
        log.warning("moments perso : %s", exc)
        rows = []

    coverage = float(samples[end - 1]["sailNm"]) if end else 0.0
    ready = end >= len(samples)
    entry.update({
        "status": "ready" if ready else "preparing",
        "moments": rows,
        "coverageNm": coverage if not ready else total_nm,
        "totalNm": total_nm,
        "fingerprint": entry.get("fingerprint") or voyage_fingerprint(voyage),
        "computedAt": _now_iso(),
        "skipped": skipped,
        "skippedKeys": sorted(skipped_keys),
        "done": end,
        "voyageId": voyage.get("voyageId"),
    })
    return entry


def moments_for_voyage(
    voyage: dict,
    *,
    budget_nm: float = DEFAULT_BUDGET_NM,
    bag_fn: Optional[Callable[[float, float], Any]] = None,
) -> dict:
    """Calcule (ou relit) les moments du voyage perso. Jamais 500, jamais de LLM."""
    if not isinstance(voyage, dict):
        return preparing_payload(None, reason="voyage absent")
    fp = voyage_fingerprint(voyage)
    cached = _load_entry(fp)
    if cached and cached.get("status") == "ready":
        return _public(cached)

    if not _COMPUTE_LOCK.acquire(blocking=False):
        if cached:
            body = _public(cached)
            body["status"] = "preparing"
            return body
        return preparing_payload(voyage, fingerprint=fp)

    try:
        cached = _load_entry(fp)
        if cached and cached.get("status") == "ready":
            return _public(cached)
        samples = sample_route_nm(voyage.get("points") or [])
        entry = cached or {
            "status": "preparing",
            "moments": [],
            "coverageNm": 0.0,
            "totalNm": float(samples[-1]["sailNm"]) if samples else 0.0,
            "fingerprint": fp,
            "computedAt": _now_iso(),
            "skipped": 0,
            "skippedKeys": [],
            "done": 0,
            "voyageId": voyage.get("voyageId"),
        }
        if not samples:
            entry.update({
                "status": "ready",
                "coverageNm": 0.0,
                "totalNm": 0.0,
                "computedAt": _now_iso(),
            })
            _save_entry(fp, voyage.get("voyageId"), entry)
            return _public(entry)
        entry = _advance(voyage, samples, entry, budget_nm=budget_nm, bag_fn=bag_fn)
        _save_entry(fp, voyage.get("voyageId"), entry)
        return _public(entry)
    except Exception as exc:
        log.warning("moments_for_voyage : %s", exc)
        return preparing_payload(voyage, fingerprint=fp, reason=str(exc))
    finally:
        _COMPUTE_LOCK.release()


# ── film de ma route ─────────────────────────────────────────────────


def _film_script_rev() -> str:
    try:
        from official_store import FILM_SCRIPT_REV  # noqa: PLC0415
        return str(FILM_SCRIPT_REV)
    except Exception:
        return "rc32"


def film_cache_key(moments_fp: str, lang: str, seconds: int, style: str) -> str:
    blob = f"{moments_fp}|{_film_script_rev()}|{(lang or 'fr')[:2].lower()}|{int(seconds or 0)}|{(style or 'raw').lower()}"
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def _film_pointer_key(voyage_id: str) -> str:
    return f"id:{voyage_id}"


def drop_cached_film(voyage_id: str) -> None:
    """Supprime les entrées custom-film d'un voyage purgé. Jamais d'exception."""
    if not voyage_id:
        return
    try:
        import pearl_store  # noqa: PLC0415
        hit = pearl_store.kv_get(FILM_NS, _film_pointer_key(voyage_id))
        keys: list[str] = []
        if hit:
            val = hit.get("value")
            if isinstance(val, list):
                keys = [str(x) for x in val if x]
            elif isinstance(val, str) and val:
                keys = [val]
        pearl_store.kv_delete(FILM_NS, _film_pointer_key(voyage_id))
        for key in keys:
            pearl_store.kv_delete(FILM_NS, key)
    except Exception as exc:
        log.warning("purge custom-film %s : %s", voyage_id, exc)


def _load_film(key: str) -> Optional[dict]:
    import pearl_store  # noqa: PLC0415
    hit = pearl_store.kv_get(FILM_NS, key, max_age_s=TTL_S)
    if not hit:
        return None
    val = hit.get("value")
    return val if isinstance(val, dict) else None


def _save_film(key: str, voyage_id: str | None, entry: dict) -> None:
    import pearl_store  # noqa: PLC0415
    pearl_store.kv_put(FILM_NS, key, entry)
    if not voyage_id:
        return
    ptr = _film_pointer_key(voyage_id)
    hit = pearl_store.kv_get(FILM_NS, ptr)
    keys: list[str] = []
    if hit:
        val = hit.get("value")
        if isinstance(val, list):
            keys = [str(x) for x in val if x]
        elif isinstance(val, str) and val:
            keys = [val]
    if key not in keys:
        keys.append(key)
    pearl_store.kv_put(FILM_NS, ptr, keys)


def _moments_rows(moments: Any) -> tuple[str, list[dict], str]:
    """(status, rows, fingerprint)."""
    if isinstance(moments, dict):
        status = str(moments.get("status") or "preparing")
        rows = [r for r in (moments.get("moments") or []) if isinstance(r, dict)]
        fp = str(moments.get("fingerprint") or "")
        return status, rows, fp
    if isinstance(moments, list):
        return "ready", [r for r in moments if isinstance(r, dict)], ""
    return "preparing", [], ""


def preparing_film_payload(
    voyage: dict | None = None,
    *,
    lang: str = "fr",
    seconds: int = 150,
    style: str = "raw",
    fingerprint: str = "",
    reason: str | None = None,
) -> dict:
    from film_script import _film_seconds  # noqa: PLC0415
    secs = _film_seconds(seconds)
    out = {
        "status": "preparing",
        "reason": reason or "en préparation",
        "family": "film",
        "lang": (lang or "fr")[:2].lower(),
        "seconds": secs,
        "style": "raw",
        "chapters": [],
        "anchors": [],
        "text": "",
        "sentences": [],
        "hasWritten": False,
        "source": "rules",
        "chars": 0,
        "targetSeconds": secs,
        "estimatedSeconds": 0,
        "fingerprint": fingerprint or (voyage_fingerprint(voyage) if voyage else ""),
        "computedAt": _now_iso(),
    }
    vid = (voyage or {}).get("voyageId")
    if vid:
        out["voyageId"] = vid
    return out


def _iso_at_nm(clock: dict | None, nm: float, fallback: str | None) -> Optional[str]:
    verts = (clock or {}).get("vertices") or []
    best_iso = fallback
    best_d = 1e18
    for v in verts:
        if not isinstance(v, dict) or not v.get("iso"):
            continue
        try:
            d = abs(float(v.get("sailNm") or 0) - float(nm))
        except (TypeError, ValueError):
            continue
        if d < best_d:
            best_d = d
            best_iso = str(v.get("iso"))
    return best_iso


def _clock_sail_nm(voyage: dict, clock: dict | None) -> Optional[float]:
    verts = (clock or {}).get("vertices") or []
    if verts and isinstance(verts[-1], dict):
        try:
            return float(verts[-1].get("sailNm") or 0)
        except (TypeError, ValueError):
            pass
    marks = voyage.get("marks") or []
    if marks and isinstance(marks[-1], dict):
        try:
            nm = marks[-1].get("nm")
            if nm is None:
                nm = marks[-1].get("filmNm")
            return float(nm or 0)
        except (TypeError, ValueError):
            pass
    return None


def _clock_sea_hours(voyage: dict, clock: dict | None, t0: str, arrival: str) -> Optional[float]:
    if isinstance((clock or {}).get("seaHours"), (int, float)):
        return float(clock["seaHours"])
    from film_script import _ms  # noqa: PLC0415
    a, b = _ms(t0), _ms(arrival)
    if a is not None and b is not None and b > a:
        return (b - a) / 3_600_000.0
    return None


def _dated_voyage_stops(voyage: dict, clock: dict | None) -> list[dict]:
    from film_script import dated_marks, merge_route_marks  # noqa: PLC0415
    clock = clock if isinstance(clock, dict) else {}
    t0 = str(voyage.get("t0") or clock.get("t0") or "")
    arrival = str(clock.get("arrivalIso") or voyage.get("arrivalIso") or "")
    verts = [v for v in (clock.get("vertices") or []) if isinstance(v, dict)]
    if not arrival and verts:
        arrival = str(verts[-1].get("iso") or "")
    marks = [m for m in (voyage.get("marks") or []) if isinstance(m, dict)]
    raw: list[dict] = []
    n = len(marks)
    for i, m in enumerate(marks):
        row = dict(m)
        name = str(row.get("name") or "").strip()
        if not name:
            name = "Départ" if i == 0 else ("Arrivée" if i == n - 1 else f"Point {i}")
            row["name"] = name
        try:
            nm_f = float(row["nm"] if row.get("nm") is not None else row.get("filmNm") or 0)
        except (TypeError, ValueError):
            nm_f = 0.0
        row["nm"] = nm_f
        row.setdefault("filmNm", nm_f)
        if not row.get("iso"):
            if i == 0:
                row["iso"] = t0
            elif i == n - 1 and arrival:
                row["iso"] = arrival
            else:
                row["iso"] = _iso_at_nm(clock, nm_f, t0)
        raw.append(row)
    if not raw:
        points = [p for p in (voyage.get("points") or []) if isinstance(p, dict)]
        if points:
            first, last = points[0], points[-1]
            try:
                last_nm = float(last.get("cumNm") or last.get("filmCum") or 0)
            except (TypeError, ValueError):
                last_nm = 0.0
            raw = [{
                "name": "Départ", "nm": 0.0, "filmNm": 0.0, "iso": t0,
                "lat": first.get("lat"), "lon": first.get("lon"),
            }]
            if len(points) > 1:
                raw.append({
                    "name": "Arrivée", "nm": last_nm, "filmNm": last_nm,
                    "iso": arrival or t0, "lat": last.get("lat"), "lon": last.get("lon"),
                })
    if len(raw) == 1:
        dest = dict(raw[0])
        dest["iso"] = arrival or raw[0].get("iso")
        if dest.get("name") == raw[0].get("name"):
            dest["name"] = "Arrivée"
        raw.append(dest)
    merged = merge_route_marks(raw, clock)
    dated = dated_marks(merged)
    return dated if dated else [r for r in raw if r.get("iso") and r.get("name")]


def _voyage_open_sentences(
    *,
    start_name: str,
    dest_name: str,
    t0: str,
    sail_nm: Optional[float],
    sea_hours: Optional[float],
    lang: str,
) -> list[str]:
    from film_script import (  # noqa: PLC0415
        _en, _honest_bookend, _opening_nm_label, day_month, short_name,
        spoken_sea_days,
    )
    en = _en(lang)
    frm = short_name(start_name or "")
    dest = short_name(dest_name or "")
    when = day_month(t0, lang, year=True)
    if not frm or not dest or not when:
        return []
    first = (
        f"On {when}, departure from {frm} for {dest}."
        if en else
        f"Le {when}, départ de {frm} vers {dest}."
    )
    nm_s = _opening_nm_label(sail_nm, lang) if sail_nm is not None else ""
    days = None
    if isinstance(sea_hours, (int, float)) and sea_hours > 0:
        days = float(sea_hours) / 24.0
    days_s = spoken_sea_days(days, lang) if days is not None else ""
    second = ""
    if nm_s and days_s:
        second = f"{nm_s}, {days_s}."
    elif nm_s:
        second = f"{nm_s}."
    elif days_s:
        second = f"{days_s[0].upper()}{days_s[1:]}."
    facts = {
        "t0": t0,
        "totalNm": int(round(float(sail_nm))) if sail_nm is not None else None,
        "totalNmLabel": nm_s,
        "daysAtSea": days,
        "daysLabel": days_s,
        "from": frm,
        "to": dest,
    }
    out: list[str] = []
    for raw in (first, second):
        spoken = _honest_bookend(raw, facts, lang)
        if spoken:
            out.append(spoken)
    return out


def _voyage_close_sentence(
    *,
    dest_name: str,
    arrival_iso: str,
    arrived: bool,
    live: dict | None,
    last_window: dict | None,
    lang: str,
) -> str:
    from film_script import _close_position, _en, _honest_bookend, day_month, short_name  # noqa: PLC0415
    dest = short_name(dest_name or "")
    if arrived and arrival_iso:
        when = day_month(arrival_iso, lang)
        if not when:
            return ""
        raw = (
            f"Arrived on {when} at {dest}." if _en(lang) and dest else
            f"Arrived on {when}." if _en(lang) else
            f"Arrivé le {when} à {dest}." if dest else
            f"Arrivé le {when}."
        )
        return _honest_bookend(raw, {"arrivalIso": arrival_iso, "dest": dest}, lang)
    return _close_position(last_window or {}, live or {}, lang)


def _voyage_arrival(dest_name: str, arrival_iso: str, lang: str) -> str:
    from film_script import _en, _honest_bookend, day_month, short_name  # noqa: PLC0415
    name = short_name(dest_name or "")
    if not name:
        return ""
    when = day_month(arrival_iso, lang)
    raw = (
        f"Arrival at {name} on {when}." if _en(lang) and when else
        f"Arrival at {name}." if _en(lang) else
        f"Arrivée à {name} le {when}." if when else
        f"Arrivée à {name}."
    )
    return _honest_bookend(raw, {"arrivalIso": arrival_iso, "dest": name}, lang)


def _public_film(
    plan: dict,
    *,
    lang: str,
    seconds: int,
    fingerprint: str,
    computed_at: str,
) -> dict:
    from film_script import _sentences, film_estimated_seconds  # noqa: PLC0415
    chapters = list(plan.get("chapters") or [])
    text = " ".join(c.get("text") or "" for c in chapters if c.get("text"))
    sentences: list[str] = []
    for c in chapters:
        sentences.extend(_sentences(c.get("text") or ""))
    anchors: list[dict] = []
    for c in chapters:
        anchors.extend(a for a in (c.get("anchors") or []) if isinstance(a, dict))
    chars = int(plan.get("chars") or 0) or sum(len(c.get("text") or "") for c in chapters)
    secs = int(plan["targetSeconds"]) if plan.get("targetSeconds") is not None else int(seconds or 0)
    return {
        "status": "ready",
        "lang": (lang or "fr")[:2].lower(),
        "seconds": secs,
        "style": "raw",
        "chapters": chapters,
        "anchors": anchors,
        "text": text,
        "sentences": sentences,
        "hasWritten": False,
        "source": "rules",
        "chars": chars,
        "targetSeconds": secs,
        "estimatedSeconds": film_estimated_seconds(chars),
        "estimates": {
            (lang or "fr")[:2].lower(): {
                str(secs): {
                    "chars": chars,
                    "estimatedSeconds": film_estimated_seconds(chars),
                },
            },
        },
        "fingerprint": fingerprint,
        "computedAt": computed_at,
        "storedAt": computed_at,
        "dataDate": (computed_at or "")[:10],
    }


def _compose_voyage_film(
    voyage: dict,
    rows: list[dict],
    *,
    lang: str,
    seconds: int,
    now: datetime,
) -> dict:
    """Chapitres : ouverture (horloge) + une jambe par paire de points + clôture."""
    global _FILM_BUILDS
    _FILM_BUILDS += 1
    from film_script import (  # noqa: PLC0415
        FILM_CHAPTER_FLOOR,
        _bubble_from_change,
        _chapter_dest,
        _climo_from_clock,
        _clock_time_near_place,
        _dest_culture_changes,
        _facts_with_rounded,
        _film_seconds,
        _first_leg_moment_ms,
        _flatten_changes,
        _iso,
        _moment_is_air,
        _ms,
        _order_chapter_sentences,
        _public_plan,
        _retarget_anchor,
        _trim_script_to_char_budget,
        _window_depart_ms,
        _window_dest_name,
        _windows,
        allocate_chapter_budgets,
        change_place_name,
        change_sentence,
        chapter_anchors,
        film_char_budget,
        film_estimated_seconds,
        film_has_forbidden,
        film_priority_tier,
        fit_chapter_text,
        looks_english_title,
        same_stop,
        script_chars,
        select_chapter_changes,
        short_name,
        speak_film_text,
        thin_chapter_dates,
    )
    from story_cascade import filter_numbers  # noqa: PLC0415

    clock = _clock_for(voyage) or (voyage.get("clock") if isinstance(voyage.get("clock"), dict) else {}) or {}
    t0 = str(voyage.get("t0") or clock.get("t0") or "")
    stops = _dated_voyage_stops(voyage, clock)
    arrival_iso = str(clock.get("arrivalIso") or voyage.get("arrivalIso") or "")
    if not arrival_iso and stops:
        arrival_iso = str(stops[-1].get("iso") or "")
    t0_ms = _ms(t0)
    arrival_ms = _ms(arrival_iso)
    now_ms = int(now.timestamp() * 1000)
    if t0_ms is None:
        return {"chapters": [], "source": "rules", "chars": 0, "targetSeconds": _film_seconds(seconds)}
    arrived = arrival_ms is not None and now_ms >= arrival_ms
    t_end = arrival_ms if arrived and arrival_ms is not None else now_ms
    if t_end <= t0_ms:
        t_end = t0_ms + 1000
    windows = _windows(stops, t0_ms, t_end, clock)
    start_name = str((stops[0].get("name") if stops else "") or "")
    dest_name = str((stops[-1].get("name") if len(stops) > 1 else start_name) or "")
    sail_nm = _clock_sail_nm(voyage, clock)
    sea_hours = _clock_sea_hours(voyage, clock, t0, arrival_iso)
    try:
        from voyage_clock import sample_clock_at_time  # noqa: PLC0415
        live = sample_clock_at_time(clock, now) or {}
    except Exception:
        live = {}
    if arrived:
        live = {**live, "atStop": dest_name, "status": "arrived"}

    has_budget = _film_seconds(seconds) > 0
    budget_s = _film_seconds(seconds)
    tier = film_priority_tier(seconds)
    n_body = max(1, len(windows))
    if has_budget:
        target = film_char_budget(budget_s)
        days = [max(1.0, ((w["tB"] - w["tA"]) / 86_400_000.0) if w else 1.0) for w in windows] or [1.0]
        # ouverture + jambes
        days = [1.0] + days
        budgets = allocate_chapter_budgets(days, target)
    else:
        target = 0
        budgets = [0] * (1 + n_body)

    opens = _voyage_open_sentences(
        start_name=start_name, dest_name=dest_name, t0=t0,
        sail_nm=sail_nm, sea_hours=sea_hours, lang=lang,
    )
    chapters: list[dict] = []
    cited: set[str] = set()

    def _pack_chapter(wid: str, t_a: int, t_b: int, text: str, anchored: list, events: list, w: dict | None) -> dict:
        w = w or {}
        return {
            "id": wid,
            "tA": _iso(t_a),
            "tB": _iso(t_b),
            "text": text,
            "anchors": chapter_anchors(text, anchored, t_a, t_b, lang),
            "events": events,
            "fromName": w.get("fromName") or (start_name if wid == "leg-open" else ""),
            "toName": w.get("toName") or (dest_name if wid == "leg-open" else ""),
            "fromLat": w.get("fromLat") if w.get("fromLat") is not None else (stops[0].get("lat") if stops else None),
            "fromLon": w.get("fromLon") if w.get("fromLon") is not None else (stops[0].get("lon") if stops else None),
            "toLat": w.get("toLat") if w.get("toLat") is not None else (stops[-1].get("lat") if stops else None),
            "toLon": w.get("toLon") if w.get("toLon") is not None else (stops[-1].get("lon") if stops else None),
        }

    open_tb = t0_ms + 1000
    if opens:
        open_text = speak_film_text(" ".join(opens), lang)
        open_anchored = [(sent, t0_ms, {"role": "depart"}) for sent in opens]
        chapters.append(_pack_chapter(
            "leg-open", t0_ms, open_tb, open_text, open_anchored, [],
            {"fromName": start_name, "toName": dest_name,
             "fromLat": stops[0].get("lat") if stops else None,
             "fromLon": stops[0].get("lon") if stops else None,
             "toLat": stops[-1].get("lat") if stops else None,
             "toLon": stops[-1].get("lon") if stops else None},
        ))
    elif not windows:
        # sans noms on ne invente pas une phrase ; un chapitre vide n'est pas un film
        return {"chapters": [], "source": "rules", "chars": 0, "targetSeconds": budget_s}

    for i, w in enumerate(windows):
        dest = _chapter_dest(w)
        dest_name_w = _window_dest_name(w) or dest_name
        arrived_w = bool(w.get("arrived")) if "arrived" in w else bool(dest)
        depart_ms = _window_depart_ms(w) or w.get("tA") or t0_ms
        first_leg = _first_leg_moment_ms(rows, w)
        if depart_ms and first_leg and (w.get("tA") or 0) < first_leg < depart_ms:
            depart_ms = first_leg
        w["departMs"] = depart_ms
        sail_moments = [m for m in rows if isinstance(m, dict) and not _moment_is_air(m)]
        flat = _flatten_changes(sail_moments, w["tA"], w["tB"], first=i == 0)
        clock_climo = _climo_from_clock(w.get("clock") or clock, w["tA"], w["tB"], first=i == 0)
        if clock_climo:
            flat = [c for c in flat if str(c.get("kind") or "") != "climo"]
            flat.extend(clock_climo)
        for extra in _dest_culture_changes(dest):
            extra = {**extra, "t": (dest or {}).get("iso"), "tMs": w["tB"]}
            flat.append(extra)
        selected = select_chapter_changes(
            flat, w["tA"], w["tB"], budget=has_budget, tier=tier if has_budget else None,
            clock=w.get("clock") or clock, depart_ms=depart_ms,
        )
        bits: list[str] = []
        placed: list[dict] = []
        anchored: list = []

        def speak_change(change: dict) -> None:
            if change.get("kind") in {"escale", "marina"}:
                return
            title = short_name(change.get("title") or "")
            if change.get("kind") == "approche" and dest_name_w and title and (
                same_stop(title, dest_name_w) or dest_name_w.casefold() in title.casefold()
            ):
                return
            place = change_place_name(change) or title
            if looks_english_title(place) and change.get("kind") in {
                "port", "approche", "culture", "project", "amp", "marina",
            }:
                return
            sentence = change_sentence(change, lang).strip()
            if not sentence or film_has_forbidden(sentence):
                return
            filtered, _dropped = filter_numbers(sentence, _facts_with_rounded(change))
            sentence = (filtered or "").strip()
            if not sentence or film_has_forbidden(sentence):
                return
            char_idx = len(" ".join(bits)) + (1 if bits else 0)
            bits.append(sentence)
            extra = {"place": place, "kind": str(change.get("kind") or "")}
            if change.get("lat") is not None:
                extra["lat"] = change.get("lat")
                extra["lon"] = change.get("lon")
            t_ms = change.get("tMs")
            near = _clock_time_near_place(
                w.get("clock") or clock, place, w["tA"], w["tB"],
                (w.get("clock") or clock or {}).get("marks"),
            )
            if near is not None:
                t_ms = near
            anchored.append((sentence, t_ms, extra))
            placed.append(_bubble_from_change(change, w, lang, char_idx))

        for change in selected:
            speak_change(change)
        arrival_iso_w = (dest or {}).get("iso") or (arrival_iso if i == len(windows) - 1 else "")
        if arrived_w and dest_name_w:
            arrival = _voyage_arrival(dest_name_w, str(arrival_iso_w or arrival_iso), lang)
            norm = dest_name_w.casefold()
            if arrival and norm not in cited:
                bits.append(arrival)
                anchored.append((arrival, w["tB"], {"role": "arrive", "place": dest_name_w, "kind": "escale"}))
                cited.add(norm)
        _order_chapter_sentences(bits, anchored, placed)
        thinned = thin_chapter_dates(bits, lang)
        if len(thinned) == len(bits) and len(anchored) == len(bits):
            anchored[:] = [_retarget_anchor(anchored[j], thinned[j]) for j in range(len(thinned))]
        bits[:] = thinned
        chapter_budget = budgets[i + 1] if i + 1 < len(budgets) else (FILM_CHAPTER_FLOOR if has_budget else 0)
        text = fit_chapter_text(" ".join(bits), chapter_budget, [], lang)
        if i == len(windows) - 1:
            close = _voyage_close_sentence(
                dest_name=dest_name_w or dest_name, arrival_iso=arrival_iso,
                arrived=arrived, live=live, last_window=w, lang=lang,
            )
            if close and close not in text:
                text = speak_film_text(f"{text} {close}".strip(), lang)
                anchored.append((close, w["tB"]))
        if not text.strip():
            # jambe muette : on garde quand même l'arrivée / la clôture déjà fusionnées
            continue
        chapters.append(_pack_chapter(w.get("id") or f"leg-{i}", w["tA"], w["tB"], text, anchored, placed, w))

    if windows and chapters and chapters[-1].get("id") == "leg-open":
        # toutes les jambes muettes : clôture sur l'ouverture
        close = _voyage_close_sentence(
            dest_name=dest_name, arrival_iso=arrival_iso,
            arrived=arrived, live=live, last_window=windows[-1], lang=lang,
        )
        last = chapters[-1]
        if close and close not in (last.get("text") or ""):
            last["text"] = speak_film_text(f"{last.get('text') or ''} {close}".strip(), lang)
            last["anchors"] = chapter_anchors(
                last["text"],
                [(s, t0_ms, {"role": "depart"}) for s in opens] + [(close, t_end)],
                t0_ms, t_end, lang,
            )

    if has_budget and target > 0:
        _trim_script_to_char_budget(chapters, int(target * 1.1))
    chars = script_chars(chapters)
    raw = {
        "chapters": chapters,
        "source": "rules",
        "chars": chars,
        "targetSeconds": budget_s,
        "estimatedSeconds": film_estimated_seconds(chars),
    }
    return _public_plan(raw, "rules")


def film_for_voyage(
    voyage: dict,
    moments: Any,
    lang: str = "fr",
    seconds: int = 150,
    style: str = "raw",
    *,
    now: datetime | None = None,
) -> dict:
    """Film brut d'un voyage perso. Jamais 500, jamais de LLM, jamais le stock officiel."""
    from film_script import _film_seconds  # noqa: PLC0415
    lg = (lang or "fr")[:2].lower()
    secs = _film_seconds(seconds)
    if not isinstance(voyage, dict):
        return preparing_film_payload(None, lang=lg, seconds=secs, style=style, reason="voyage absent")
    status, rows, mom_fp = _moments_rows(moments)
    mom_fp = mom_fp or voyage_fingerprint(voyage)
    if status != "ready":
        return preparing_film_payload(
            voyage, lang=lg, seconds=secs, style=style, fingerprint=mom_fp,
        )
    key = film_cache_key(mom_fp, lg, secs, "raw")
    cached = _load_film(key)
    if cached and cached.get("status") == "ready" and (cached.get("chapters") or []):
        return cached

    if not _FILM_LOCK.acquire(blocking=False):
        if cached:
            body = dict(cached)
            body["status"] = "preparing"
            return body
        return preparing_film_payload(voyage, lang=lg, seconds=secs, style=style, fingerprint=mom_fp)

    try:
        cached = _load_film(key)
        if cached and cached.get("status") == "ready" and (cached.get("chapters") or []):
            return cached
        when = now if isinstance(now, datetime) else datetime.now(timezone.utc)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        plan = _compose_voyage_film(voyage, rows, lang=lg, seconds=secs, now=when)
        computed = _now_iso()
        out = _public_film(plan, lang=lg, seconds=secs, fingerprint=key, computed_at=computed)
        if out.get("voyageId") is None and voyage.get("voyageId"):
            out["voyageId"] = voyage.get("voyageId")
        if out.get("chapters"):
            _save_film(key, voyage.get("voyageId"), out)
        return out
    except Exception as exc:
        log.warning("film_for_voyage : %s", exc)
        return preparing_film_payload(
            voyage, lang=lg, seconds=secs, style=style, fingerprint=mom_fp, reason=str(exc),
        )
    finally:
        _FILM_LOCK.release()
