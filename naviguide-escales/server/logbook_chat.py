"""Chatbot journal de bord — CH1 (faits par les règles, Ultra si le juge est ouvert).

Le skipper pose une question sur **toutes les données de l'application**.
Le serveur assemble un paquet de faits ; le modèle ne les invente pas.

1. Lightning (`fast`) classe (intention, lieu, date). Éteint ou au plafond →
   analyseur par mots-clés (pourquoi / comment / longueur, FR et EN).
2. Question simple : les règles répondent depuis le paquet (`source=rules`),
   chaque nombre copié, `filter_numbers`. Super (`write`) ne rédige jamais.
3. Question difficile (pourquoi, comment, ou assez longue) : un appel Ultra
   (`judge`) si `allow("judge")`, puis `filter_numbers`. Juge coupé (défaut
   du dépôt) → la même réponse de règles, zéro appel write.

Un chiffre ne passe jamais par le LLM : `filter_numbers` reste juge.
`failed` ne reste que si même le gabarit de faits est impossible.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from admin_guard import is_admin, rate_limited
from ai_transparency import enrich_llm_payload
from story_cascade import TOKENFACTORY_BASE, _clean_text, cascade_text, nebius_key, tidy_story

log = logging.getLogger("naviguide-simulator.logbook")

router = APIRouter()

QUESTION_MAX = 500
CONTEXT_MAX_BYTES = 12_000
ANSWER_SENTENCES = 3
ULTRA_SENTENCES = 5
ANSWER_CHARS = 480
ULTRA_CHARS = 720
JOURNAL_TAIL = 40
JOURNAL_EVENT_KINDS = (
    "stop", "grib", "note", "zee", "amp", "poe", "wx", "chat",
    "climo", "sci", "news", "project",
)
JOURNAL_SLIM_KEYS = (
    "kind", "t", "event", "name", "text", "summary",
    "windKnots", "dirFromDeg", "hs", "holdHours", "daysAtQuay",
    "level", "model", "nm", "inside", "source",
)
JOURNAL_PER_KIND = 8
FACT_TOKEN_CAP = 6_000
PARSE_MAX_TOKENS = 256
PLAN_LEGS_MAX = 12

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+(?=[^\s])")
_WHY_RE = re.compile(r"(?i)(?<!\w)(pourquoi|comment|why|how)(?!\w)")
_ROUTE_RE = re.compile(
    r"(?i)(?<!\w)(route|itinéraire|itineraire|trajet|leg|jambe|waypoint|waypoints|"
    r"plan de route|route plan|course|routing)(?!\w)",
)
FAST_QUESTION_MAX = 80
WX_MEMORY = 200
_WX_WORDS = re.compile(
    r"(?i)(n[œoe]uds?|knots?|vent|wind|gale|coup de vent|rafale|hs|vague|mer|sea|houle|force)",
)
_SEA_WORDS = re.compile(r"(?i)(hs|vague|mer|sea|houle)")
_SPEED_WORDS = re.compile(r"(?i)(?<!polaire\s)(?<!polar\s)(vitesse|speed|quai|quay|ralentir|slow(?:ing|\s+down)?)(?!\s*polaire)(?!\s*polar)")
_STOP_WORDS = re.compile(r"(?i)(escale|stopover|prochaine|next\s+stop|destination)")
_HEADING_WORDS = re.compile(r"(?i)(?<!\w)(cap|heading|cog)(?!\w)")
_POLAR_WORDS = re.compile(r"(?i)(polaire|polar|vmg)")
_ETA_WORDS = re.compile(r"(?i)(arriv[ée]e|eta|fourchette|expected arrival|arrival)")
_DEPTH_WORDS = re.compile(r"(?i)(profondeur|depth|bathy)")
_ZEE_WORDS = re.compile(r"(?i)(zee|z\.?e\.?e\.?|zone économique|exclusive economic)")
_PROJECT_WORDS = re.compile(r"(?i)(projets?|projects?)")
_CLIMO_WORDS = re.compile(r"(?i)(climatolog|climo)")
_SETTING_WORDS = re.compile(
    r"(?i)(r[ée]glage|setting|confort|comfort|horizon|profil|profile|knob)",
)
_POSITION_WORDS = re.compile(r"(?i)(o[ùu] est le bateau|where is the boat|position)")
_REASON_WORDS = re.compile(
    r"(?i)(pourquoi|comment|why|how|faut-il|should we|should i|comparer|"
    r"compare|que faire|what if|attendre|or wait|conseil|advice|mieux vaut|"
    r"better to|partir demain)",
)
_REASON_PREFIX_RE = re.compile(r"(?i)^\s*(raisonne|raisonnement|reason(?:ing)?)\s*[:\-]\s*")
_JSON_OBJ_RE = re.compile(r"\{.*\}", re.S)
_MISSING_FR = "Le journal n’a pas cette information dans ses données."
_MISSING_EN = "The logbook does not hold that information in its data."
DC_FAMILY_KINDS = (
    "amp", "buoy", "poe", "anchorage", "aton", "cable", "depth", "piracy", "satellite",
)
EMBED_MODEL = "Qwen/Qwen3-Embedding-8B"
EMBED_MIN_COS = 0.25
_POLAR_TWS = (10, 15, 20, 25)
_MONTH_NAMES = {
    "janvier": 1, "january": 1, "jan": 1,
    "février": 2, "fevrier": 2, "february": 2, "feb": 2,
    "mars": 3, "march": 3, "mar": 3,
    "avril": 4, "april": 4, "apr": 4,
    "mai": 5, "may": 5,
    "juin": 6, "june": 6, "jun": 6,
    "juillet": 7, "july": 7, "jul": 7,
    "août": 8, "aout": 8, "august": 8, "aug": 8,
    "septembre": 9, "september": 9, "sept": 9, "sep": 9,
    "octobre": 10, "october": 10, "oct": 10,
    "novembre": 11, "november": 11, "nov": 11,
    "décembre": 12, "decembre": 12, "december": 12, "dec": 12,
}
_QTY_ALIASES = {
    "vent": "wind", "wind": "wind", "rafale": "wind", "gale": "wind",
    "vitesse": "speed", "speed": "speed",
    "cap": "heading", "heading": "heading", "cog": "heading",
    "eta": "eta", "arrivée": "eta", "arrivee": "eta", "arrival": "eta",
    "fourchette": "eta",
    "profondeur": "depth", "depth": "depth", "bathy": "depth",
    "escale": "next_stop", "stop": "next_stop", "stopover": "next_stop",
    "zee": "zee",
    "projet": "projects", "project": "projects", "projects": "projects",
    "climatologie": "climo", "climatology": "climo", "climo": "climo",
    "réglage": "setting", "reglage": "setting", "setting": "setting",
    "confort": "setting", "comfort": "setting",
    "polaire": "polar", "polar": "polar", "vmg": "polar",
    "position": "position", "lieu": "position",
    "couche": "layer", "layer": "layer",
    "cable": "cables", "câble": "cables", "cables": "cables",
}
# Capitalized leftovers that are not a toponym (« Arrivée prévue ? »).
_PLACE_SKIP = frozenset({
    "quel", "quelle", "quels", "quelles", "what", "the",
    "arrivee", "arrival", "expected", "prevue", "eta",
    "fourchette", "window",
})


# ── context ─────────────────────────────────────────────────────────────────

def _slim_places(items: Any, n: int = 4) -> list[dict]:
    out = []
    for it in items or []:
        if isinstance(it, dict) and it.get("name"):
            row = {"name": it["name"]}
            if isinstance(it.get("nm"), (int, float)):
                row["nm"] = round(float(it["nm"]), 1)
            out.append(row)
        if len(out) >= n:
            break
    return out


def _next_stop(clock: dict | None, now: datetime) -> Optional[dict]:
    if not clock:
        return None
    from voyage_clock import parse_iso  # noqa: PLC0415
    t0 = parse_iso(clock["t0"])
    for m in clock.get("marks") or []:
        if m.get("tHours") is None or not m.get("name"):
            continue
        from datetime import timedelta  # noqa: PLC0415
        eta = t0 + timedelta(hours=float(m["tHours"]))
        if eta > now:
            return {"name": m["name"], "eta": eta.isoformat().replace("+00:00", "Z"), "holdDays": round(float(m.get("holdHours") or 0) / 24)}
    return None


def _spoken_title(title: Any) -> str | None:
    if isinstance(title, dict):
        text = title.get("fr") or title.get("en")
        return str(text).strip() if text else None
    if title:
        text = str(title).strip()
        return text or None
    return None


def _slim_journal_entry(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict) or not entry.get("kind"):
        return None
    row: dict[str, Any] = {}
    for key in JOURNAL_SLIM_KEYS:
        value = entry.get(key)
        if value is not None and value != "":
            row[key] = value
    title = _spoken_title(entry.get("title"))
    if title and not row.get("name"):
        row["name"] = title
    facts = entry.get("facts")
    if isinstance(facts, dict) and facts:
        row["facts"] = facts
    return row


def _journal_sig(entry: dict) -> str:
    return str(entry.get("id") or f"{entry.get('kind')}:{entry.get('t')}:{entry.get('name') or ''}")


def _per_kind_tail(rows: list[dict], n: int = JOURNAL_PER_KIND) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        buckets.setdefault(str(entry.get("kind") or "?"), []).append(entry)
    out: list[dict] = []
    for items in buckets.values():
        out.extend(items[-n:])
    return out


def _official_journal_rows(kinds: tuple[str, ...]) -> list[dict]:
    """Same logbook the UI reads (official_store), not the thin file journal."""
    try:
        import official_store  # noqa: PLC0415
        payload = official_store.serve_journal(max(JOURNAL_TAIL, 80), kinds)
    except Exception:
        return []
    if not isinstance(payload, dict) or payload.get("status") != "ready":
        return []
    latest = [e for e in (payload.get("latest") or []) if isinstance(e, dict)]
    events = [e for e in (payload.get("events") or []) if isinstance(e, dict)]
    return _per_kind_tail(events) + [e for e in latest if e.get("kind") != "position"]


def journal_for_chat(limit: int = JOURNAL_TAIL) -> list[dict]:
    """Official voyage logbook for Ultra / Super — AMP, ZEE, stops, news, chats."""
    import voyage_journal as journal  # noqa: PLC0415

    merged: list[dict] = []
    seen: set[str] = set()
    for entry in _official_journal_rows(JOURNAL_EVENT_KINDS) + journal.latest(limit, kinds=JOURNAL_EVENT_KINDS):
        slim = _slim_journal_entry(entry)
        if not slim:
            continue
        sig = _journal_sig(entry)
        if sig in seen:
            continue
        seen.add(sig)
        merged.append(slim)
    merged.sort(key=lambda row: str(row.get("t") or ""), reverse=True)
    try:
        import escale_watch  # noqa: PLC0415

        merged = escale_watch.drop_news_if_in_film(merged)
    except Exception:
        pass
    return merged[:limit]


_AROUND_WORDS = re.compile(
    r"(?i)(amp|mpa|aire marine|protected area|zee|eez|port|marina|around|"
    r"autour|pr[eè]s|near|nearby|formalit)",
)


def _mark_short_name(name: str) -> str:
    return str(name or "").split("(")[0].strip()


def stop_in_question(question: str, clock: dict | None) -> dict | None:
    """Longest official-stop name that appears in the question, if any."""
    q = (question or "").casefold()
    if not q or not isinstance(clock, dict):
        return None
    best: tuple[int, dict] | None = None
    for mark in clock.get("marks") or []:
        if not isinstance(mark, dict):
            continue
        short = _mark_short_name(str(mark.get("name") or ""))
        if len(short) < 4 or short.casefold() not in q:
            continue
        lat, lon = mark.get("lat"), mark.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        if best is None or len(short) > best[0]:
            best = (len(short), mark)
    return None if best is None else best[1]


def _around_point(question: str, clock: dict | None, boat_lat, boat_lon):
    """Named stop first (Papeete AMP while the boat is at Mata-Utu). Else the boat."""
    hit = stop_in_question(question, clock)
    if hit is not None:
        return float(hit["lat"]), float(hit["lon"]), "stop"
    if boat_lat is not None and boat_lon is not None and _AROUND_WORDS.search(question or ""):
        return float(boat_lat), float(boat_lon), "boat"
    if boat_lat is not None and boat_lon is not None:
        return float(boat_lat), float(boat_lon), "boat"
    return None


async def build_context(
    client_ctx: dict | None,
    now: datetime,
    http: httpx.AsyncClient | None = None,
    question: str | None = None,
) -> dict[str, Any]:
    """The facts the bot may cite. Nothing here comes from the model."""
    from voyage_api import _grib_around_from_live, _latest_official_grib, _now  # noqa: PLC0415
    from voyage_clock import OFFICIAL_VOYAGE_ID, sample_clock_at_time  # noqa: PLC0415
    from voyage_store import load_voyage  # noqa: PLC0415
    from saildocs import wind_at_daily  # noqa: PLC0415

    ctx: dict[str, Any] = {"now": now.isoformat().replace("+00:00", "Z")}
    client_ctx = client_ctx if isinstance(client_ctx, dict) else {}
    view = str(client_ctx.get("view") or "suivre")[:12]
    ctx["view"] = view

    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    clock = (voy or {}).get("clock")
    live = None
    if clock:
        sample = sample_clock_at_time(clock, now)
        if sample and sample.get("lat") is not None:
            at_quay = bool(sample.get("atQuay"))
            planned = sample.get("plannedKnots")
            if planned is None and not at_quay:
                planned = sample.get("speedKnots")
            boat_in = client_ctx.get("boat") if isinstance(client_ctx.get("boat"), dict) else None
            measured = boat_in.get("speedKnots") if boat_in is not None else None
            measured = float(measured) if isinstance(measured, (int, float)) else None
            regime = sample.get("regime") or sample.get("kind") or "climatology"
            # En Suivre, une seule vitesse — celle de l'horloge (0 à quai).
            if at_quay:
                speed, basis = 0, "clock"
            elif view == "suivre":
                speed, basis = sample.get("speedKnots"), "clock"
            elif measured is not None:
                speed, basis = measured, "measured"
            else:
                speed, basis = sample.get("speedKnots"), "clock"
            live = {
                "lat": round(float(sample["lat"]), 3),
                "lon": round(float(sample["lon"]), 3),
                "sailNm": round(float(sample.get("sailNm") or 0)),
                "speedKnots": speed,
                "plannedKnots": planned,
                "atQuay": at_quay,
                "status": sample.get("status"),
                "basis": basis,
                "regime": regime,
            }
            try:
                around = _grib_around_from_live(voy, now)
                grib = _latest_official_grib(around, now)
                wind = wind_at_daily(grib, float(sample["lat"]), float(sample["lon"]), now)
                if wind:
                    live["wind"] = {k: wind.get(k) for k in ("windKnots", "dirFromDeg", "pressHpa", "rainMm", "hs", "model") if wind.get(k) is not None}
                    live["wind"]["kind"] = "forecast"
                else:
                    live["wind"] = {"kind": "absent"}
            except Exception as exc:
                live["wind"] = {"kind": "absent", "reason": type(exc).__name__}
    ctx["official"] = live
    ctx["nextStop"] = _next_stop(clock, now)

    # The boat the question is about: the official one, or the film boat the client sent.
    boat = client_ctx.get("boat") if isinstance(client_ctx.get("boat"), dict) else None
    lat = lon = None
    if boat and isinstance(boat.get("lat"), (int, float)) and isinstance(boat.get("lon"), (int, float)):
        lat, lon = float(boat["lat"]), float(boat["lon"])
        boat_out = {
            "lat": round(lat, 3),
            "lon": round(lon, 3),
            "basis": "simulation" if view != "suivre" else "clock",
            "iso": boat.get("iso"),
        }
        if view == "suivre" and live is not None and live.get("speedKnots") is not None:
            boat_out["speedKnots"] = float(live["speedKnots"])
            boat_out["atQuay"] = bool(live.get("atQuay"))
            if live.get("regime"):
                boat_out["regime"] = live["regime"]
        elif isinstance(boat.get("speedKnots"), (int, float)):
            boat_out["speedKnots"] = float(boat["speedKnots"])
            if boat.get("regime"):
                boat_out["regime"] = boat["regime"]
        ctx["boat"] = boat_out
    elif live:
        lat, lon = live["lat"], live["lon"]
        boat_out = {"lat": lat, "lon": lon, "basis": "clock"}
        if live.get("speedKnots") is not None:
            boat_out["speedKnots"] = float(live["speedKnots"])
        if live.get("regime"):
            boat_out["regime"] = live["regime"]
        boat_out["atQuay"] = bool(live.get("atQuay"))
        ctx["boat"] = boat_out

    bag = None
    point = _around_point(question or "", clock, lat, lon)
    if point is not None:
        around_lat, around_lon, around_basis = point
        try:
            from ici_engine import fill_dossier  # noqa: PLC0415
            bag = await fill_dossier(around_lat, around_lon, 30.0, client=http, thin=True, rich=True)
            nearby = bag.get("nearby") or {}
            science = bag.get("science")
            ctx["around"] = {
                "at": {"lat": round(around_lat, 3), "lon": round(around_lon, 3), "basis": around_basis},
                "zee": {k: (bag.get("zee") or {}).get(k) for k in ("name", "mrgid", "gold") if (bag.get("zee") or {}).get(k) is not None} or None,
                "portsOfEntry": _slim_places(bag.get("poe")),
                "protectedAreas": _slim_places(bag.get("amp")),
                "marinas": _slim_places(nearby.get("marinas")),
                "harbourMasters": _slim_places(nearby.get("capitaineries"), 2),
                "ports": _slim_places(nearby.get("wpi"), 3),
                "projects": _slim_places(bag.get("projects"), 3),
                "science": _slim_places(science.get("nearby") if isinstance(science, dict) else science, 3),
                "aidsToNavigation": _slim_places((bag.get("aton") or {}).get("nearby"), 3),
                "depthM": ((bag.get("emodnet") or {}).get("bathy") or {}).get("depth_m"),
            }
        except Exception as exc:
            ctx["around"] = {"reason": f"unavailable:{type(exc).__name__}"}
            bag = None

    ctx["journal"] = journal_for_chat()

    # What only the client knows: its polar, its skipper's orders, its view.
    for key in ("polar", "orders", "leg"):
        val = client_ctx.get(key)
        if isinstance(val, dict):
            ctx[key] = val

    ctx["polar"] = _polar_facts(client_ctx, ctx.get("polar") if isinstance(ctx.get("polar"), dict) else None)
    ctx["orders"] = _orders_facts(ctx.get("orders") if isinstance(ctx.get("orders"), dict) else None)
    ctx["plan"] = _plan_facts(now, clock)
    ctx["climo"] = _climo_facts(lat, lon, now.month)
    ctx["layers"] = _layers_facts(ctx.get("around") if isinstance(ctx.get("around"), dict) else None, bag)
    ctx["dcFamilies"] = _dc_facts(bag)
    try:
        import port_web_context  # noqa: PLC0415

        await port_web_context.attach(ctx, http, now)
    except Exception:
        ctx["portWeb"] = {"status": "unavailable", "reason": "error", "sources": []}
    return bound_facts(ctx)


def _fold(text: str) -> str:
    raw = unicodedata.normalize("NFD", str(text or ""))
    return "".join(ch for ch in raw if unicodedata.category(ch) != "Mn").lower()


def estimate_tokens(obj: Any) -> int:
    blob = json.dumps(obj, ensure_ascii=False, default=str)
    return max(1, (len(blob) + 3) // 4)


def _trim_list(items: Any, n: int) -> list:
    if not isinstance(items, list):
        return []
    return list(items[: max(0, n)])


def bound_facts(ctx: dict, cap: int = FACT_TOKEN_CAP) -> dict:
    """Truncate lists so the pack stays ≤ cap tokens. Never drop a number field."""
    if not isinstance(ctx, dict):
        return {}
    around = ctx.get("around") if isinstance(ctx.get("around"), dict) else None
    plan = ctx.get("plan") if isinstance(ctx.get("plan"), dict) else None
    limits = (8, 4, 2)
    for n in limits:
        if estimate_tokens(ctx) <= cap:
            break
        ctx["journal"] = _trim_list(ctx.get("journal"), n)
        if around:
            for key in (
                "portsOfEntry", "protectedAreas", "marinas", "harbourMasters",
                "ports", "projects", "science", "aidsToNavigation",
            ):
                around[key] = _trim_list(around.get(key), min(n, 4))
            ctx["around"] = around
        if plan and isinstance(plan.get("legs"), list):
            plan["legs"] = _trim_list(plan["legs"], min(n, PLAN_LEGS_MAX))
            ctx["plan"] = plan
        layers = ctx.get("layers") if isinstance(ctx.get("layers"), dict) else None
        if layers:
            for key in ("protectedAreas", "projects"):
                if isinstance(layers.get(key), list):
                    layers[key] = _trim_list(layers[key], min(n, 3))
            ctx["layers"] = layers
        if isinstance(ctx.get("dcFamilies"), list):
            ctx["dcFamilies"] = _trim_list(ctx["dcFamilies"], min(n, len(DC_FAMILY_KINDS)))
    return ctx


def _polar_from_engine(polar) -> dict[str, Any] | None:
    if polar is None:
        return None
    speed_at: dict[str, Any] = {}
    for tws in _POLAR_TWS:
        try:
            kn = polar.speed(90.0, float(tws))
        except Exception:
            kn = None
        if isinstance(kn, (int, float)) and math.isfinite(float(kn)):
            speed_at[str(tws)] = round(float(kn), 2)
    vmg_up = vmg_dn = None
    try:
        twa, bs, vmg = polar.optimal_upwind(15.0)
        vmg_up = {"twsKn": 15, "twaDeg": twa, "speedKn": bs, "vmgKn": vmg}
    except Exception:
        vmg_up = None
    try:
        twa, bs, vmg = polar.optimal_downwind(15.0)
        vmg_dn = {"twsKn": 15, "twaDeg": twa, "speedKn": bs, "vmgKn": vmg}
    except Exception:
        vmg_dn = None
    boat = getattr(polar, "boat_name", None)
    out: dict[str, Any] = {
        "unit": "kn",
        "source": "polar",
        "boat": boat,
        "speedAtTws": speed_at,
    }
    if vmg_up:
        out["vmgUpwind"] = vmg_up
    if vmg_dn:
        out["vmgDownwind"] = vmg_dn
    return out


def _polar_facts(client_ctx: dict, client_polar: dict | None) -> dict[str, Any]:
    """Résumé de table : VMG près/portant + vitesses à 10/15/20/25 kn. Fichier serveur d'abord."""
    engine = None
    try:
        from polar_api import DEFAULT_POLAR_EXPEDITION, _stored_or_default_polar  # noqa: PLC0415
        from polar_engine import PolarData  # noqa: PLC0415
        raw_client = client_polar.get("raw") if isinstance(client_polar, dict) else None
        if isinstance(raw_client, dict) and raw_client.get("twa_rows") and raw_client.get("tws_cols"):
            engine = PolarData(
                raw_client["twa_rows"],
                raw_client["tws_cols"],
                raw_client.get("matrix") or [],
                boat_name=str((client_polar or {}).get("boat") or "Boat"),
            )
        else:
            _payload, engine = _stored_or_default_polar(DEFAULT_POLAR_EXPEDITION)
    except Exception as exc:
        log.debug("polar facts : %s", exc)
        engine = None
    packed = _polar_from_engine(engine)
    if packed is None:
        if isinstance(client_polar, dict) and client_polar:
            slim = {k: client_polar.get(k) for k in ("boat", "loaM", "draftM", "planningKn") if client_polar.get(k) is not None}
            slim["unit"] = "kn"
            slim["source"] = "client"
            return slim
        return {"unit": "kn", "source": "polar", "status": "en préparation"}
    if isinstance(client_polar, dict):
        if client_polar.get("boat") and not packed.get("boat"):
            packed["boat"] = client_polar["boat"]
        for k in ("loaM", "draftM", "planningKn"):
            if client_polar.get(k) is not None:
                packed[k] = client_polar[k]
    return packed


def _orders_facts(orders: dict | None) -> dict[str, Any]:
    """Tous les knobs et valeurs skipper, pas seulement quatre champs."""
    if not isinstance(orders, dict) or not orders:
        return {"source": "skipper", "status": "en préparation"}
    values = orders.get("values") if isinstance(orders.get("values"), dict) else {}
    knobs = orders.get("knobs") if isinstance(orders.get("knobs"), dict) else {}
    expert = orders.get("expert") if isinstance(orders.get("expert"), dict) else {}
    boat = orders.get("boat") if isinstance(orders.get("boat"), dict) else {}
    out: dict[str, Any] = {
        "source": "skipper",
        "profile": orders.get("profile"),
        "comfort": orders.get("comfort") or knobs.get("comfort"),
        "knobs": knobs,
        "values": values,
        "expert": expert,
        "boat": {k: boat.get(k) for k in ("name", "loaM", "draftM", "planningKn") if boat.get(k) is not None},
    }
    budget = orders.get("budget") if isinstance(orders.get("budget"), dict) else None
    if budget:
        out["budget"] = {k: budget.get(k) for k in ("hours", "planningKn", "maxNm", "maxPearls") if budget.get(k) is not None}
    return out


def _plan_facts(now: datetime, clock: dict | None) -> dict[str, Any]:
    """Revue du plan : ETA, fourchette, alertes — stock officiel, jamais inventé."""
    out: dict[str, Any] = {"source": "plan_review", "unit": "ISO-8601", "legs": [], "status": "en préparation"}
    review = None
    eta_stops: dict = {}
    try:
        import official_store  # noqa: PLC0415
        review = official_store.serve_plan_review()
        eta_hit = official_store.get("eta")
        body = (eta_hit or {}).get("payload") if isinstance(eta_hit, dict) else None
        if isinstance(body, dict) and isinstance(body.get("stops"), dict):
            eta_stops = body["stops"]
    except Exception as exc:
        log.debug("plan facts stock : %s", exc)
    legs_in = []
    if isinstance(review, dict) and review.get("status") != "preparing":
        legs_in = [lg for lg in (review.get("legs") or []) if isinstance(lg, dict)]
        if legs_in:
            out["status"] = "ready"
    rows: list[dict[str, Any]] = []
    for lg in legs_in[:PLAN_LEGS_MAX]:
        name = lg.get("to") or lg.get("name")
        eta = eta_stops.get(name) if isinstance(name, str) else None
        if not isinstance(eta, dict):
            eta = {}
        flags = [f for f in (lg.get("flags") or []) if isinstance(f, dict)]
        row: dict[str, Any] = {
            "from": lg.get("from"),
            "to": name,
            "arriveIso": lg.get("arriveIso"),
            "holdDays": lg.get("holdDays"),
            "alertCount": lg.get("alertCount"),
            "flags": flags[:4],
        }
        for k in ("p10", "p50", "p90"):
            if eta.get(k):
                row[k] = eta[k]
        if eta.get("members") is not None:
            row["members"] = eta.get("members")
        rows.append(row)
    if not rows:
        nxt = _next_stop(clock, now)
        if nxt:
            rows.append({"to": nxt.get("name"), "arriveIso": nxt.get("eta"), "holdDays": nxt.get("holdDays")})
            out["status"] = "ready"
            out["source"] = "clock"
    out["legs"] = rows
    out["n"] = len(rows)
    return out


def _climo_facts(lat: float | None, lon: float | None, month: int) -> dict[str, Any]:
    """Vent moyen, rafales, houle au point — ce que la couche climo affiche (cache, jamais inventé)."""
    m = max(1, min(12, int(month or 1)))
    base: dict[str, Any] = {"unit": "kn", "hsUnit": "m", "month": m, "source": "climo", "status": "en préparation"}
    if lat is None or lon is None:
        return base
    wind = None
    try:
        from climatology_atlas import atlas_wind_cached  # noqa: PLC0415
        wind = atlas_wind_cached(float(lat), float(lon), m)
    except Exception as exc:
        log.debug("climo facts : %s", exc)
        wind = None
    if not isinstance(wind, dict):
        return base
    kn = wind.get("speedKnots")
    gust = None
    rose = wind.get("roseKnots")
    if isinstance(rose, (list, tuple)) and rose:
        nums = [float(x) for x in rose if isinstance(x, (int, float))]
        if nums:
            gust = max(nums)
    out: dict[str, Any] = {
        "unit": "kn",
        "hsUnit": "m",
        "month": m,
        "source": wind.get("source") or "climo",
        "status": "ready",
        "windMeanKn": kn,
        "dirFromDeg": wind.get("dirFromDeg"),
        "gustKn": gust,
        "hsM": wind.get("hs") if wind.get("hs") is not None else wind.get("hsP50"),
        "hsP90M": wind.get("hsP90"),
    }
    if kn is None and gust is None and out.get("hsM") is None:
        out["status"] = "en préparation"
    return out


def _layers_facts(around: dict | None, bag: Any) -> dict[str, Any]:
    emo = {}
    if isinstance(bag, dict):
        emo = bag.get("emodnet") if isinstance(bag.get("emodnet"), dict) else {}
    bathy = None
    cables = None
    if emo:
        bathy = (emo.get("bathy") or {}).get("depth_m") if isinstance(emo.get("bathy"), dict) else None
        cables = emo.get("cables")
    if bathy is None and isinstance(around, dict):
        bathy = around.get("depthM")
    out: dict[str, Any] = {
        "unit": "m",
        "source": "ici",
        "bathyM": bathy,
        "cables": cables,
    }
    if isinstance(around, dict):
        if around.get("zee"):
            out["zee"] = around["zee"]
        if around.get("protectedAreas"):
            out["protectedAreas"] = _trim_list(around.get("protectedAreas"), 4)
        if around.get("projects"):
            out["projects"] = _trim_list(around.get("projects"), 3)
    return out


def _dc_name(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    name = item.get("name") or item.get("title") or item.get("phrase")
    if isinstance(name, dict):
        name = _spoken_title(name)
    text = str(name).strip() if name else ""
    return text or None


def _slim_dc_row(kind: str, item: dict) -> dict[str, Any] | None:
    """Une famille DC, champs entiers — on ne coupe jamais un nombre."""
    if kind not in DC_FAMILY_KINDS or not isinstance(item, dict):
        return None
    row: dict[str, Any] = {"kind": kind}
    name = _dc_name(item)
    if name:
        row["name"] = name
    if isinstance(item.get("nm"), (int, float)):
        row["nm"] = round(float(item["nm"]), 1)
    phrase = item.get("phrase")
    if isinstance(phrase, str) and phrase.strip():
        row["phrase"] = phrase.strip()
    if kind == "depth":
        depth = item.get("depthM")
        if depth is None:
            depth = item.get("depth_m")
        if isinstance(depth, (int, float)):
            row["depthM"] = depth
    if kind == "cable" and item.get("nearby") is True:
        row["nearby"] = True
    if kind == "piracy":
        for key in ("level", "source"):
            if item.get(key) is not None and item.get(key) != "":
                row[key] = item[key]
    if len(row) <= 1:
        return None
    return row


def _dc_from_ici_bag(bag: Any) -> list[dict[str, Any]]:
    """Familles déjà dans le sac ICI. Satellite seulement s'il est jouable."""
    if not isinstance(bag, dict):
        return []
    nearby = bag.get("nearby") if isinstance(bag.get("nearby"), dict) else {}
    emo = bag.get("emodnet") if isinstance(bag.get("emodnet"), dict) else {}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(kind: str, item: Any) -> None:
        if kind in seen or not isinstance(item, dict):
            return
        row = _slim_dc_row(kind, item)
        if not row:
            return
        seen.add(kind)
        out.append(row)

    for it in bag.get("amp") or []:
        add("amp", it)
        if "amp" in seen:
            break
    for it in bag.get("poe") or []:
        add("poe", it)
        if "poe" in seen:
            break
    aton = bag.get("aton") if isinstance(bag.get("aton"), dict) else {}
    for it in aton.get("nearby") or []:
        add("aton", it)
        if "aton" in seen:
            break
    for it in nearby.get("anchorages") or []:
        add("anchorage", it)
        if "anchorage" in seen:
            break
    cables = emo.get("cables")
    if isinstance(cables, dict) and (cables.get("nearby") is True or _dc_name(cables)):
        add("cable", cables)
    bathy = emo.get("bathy") if isinstance(emo.get("bathy"), dict) else {}
    if isinstance(bathy.get("depth_m"), (int, float)):
        add("depth", {"depthM": bathy["depth_m"]})
    piracy = bag.get("piracy")
    if isinstance(piracy, dict):
        add("piracy", piracy)
    sat = bag.get("satellites")
    if isinstance(sat, dict) and (_dc_name(sat) or sat.get("id") or sat.get("url") or sat.get("scene")):
        add("satellite", sat)
    return out


def _dc_from_film_bag() -> list[dict[str, Any]]:
    """Sac VS1 déjà stocké (`dcSubjects`). Absent ou en préparation → rien."""
    try:
        import official_store  # noqa: PLC0415
        hit = official_store.get("film")
    except Exception:
        return []
    body = (hit or {}).get("payload") if isinstance(hit, dict) else None
    if not isinstance(body, dict):
        return []
    subjects = body.get("dcSubjects") if isinstance(body.get("dcSubjects"), list) else None
    if subjects is None:
        variants = body.get("variants") if isinstance(body.get("variants"), dict) else {}
        for lang_map in variants.values():
            if not isinstance(lang_map, dict):
                continue
            for plan in lang_map.values():
                if isinstance(plan, dict) and isinstance(plan.get("dcSubjects"), list):
                    subjects = plan["dcSubjects"]
                    break
            if subjects is not None:
                break
    if not isinstance(subjects, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rec in subjects:
        if not isinstance(rec, dict):
            continue
        kind = str(rec.get("kind") or "")
        if kind in seen:
            continue
        row = _slim_dc_row(kind, rec)
        if not row:
            continue
        seen.add(kind)
        out.append(row)
    return out


def _dc_facts(bag: Any) -> list[dict[str, Any]]:
    """Une entrée par famille DC, seulement si le sac la tient. Jamais inventée."""
    by_kind: dict[str, dict[str, Any]] = {}
    for row in _dc_from_film_bag() + _dc_from_ici_bag(bag):
        kind = row.get("kind")
        if kind and kind not in by_kind:
            by_kind[str(kind)] = row
    return [by_kind[k] for k in DC_FAMILY_KINDS if k in by_kind]


def apply_climo_month(ctx: dict, month: int | None) -> None:
    """Si la question nomme un mois, le paquet porte la climo de CE mois (cache)."""
    if not isinstance(ctx, dict) or not month:
        return
    boat = ctx.get("boat") if isinstance(ctx.get("boat"), dict) else {}
    official = ctx.get("official") if isinstance(ctx.get("official"), dict) else {}
    lat = boat.get("lat") if boat.get("lat") is not None else official.get("lat")
    lon = boat.get("lon") if boat.get("lon") is not None else official.get("lon")
    ctx["climo"] = _climo_facts(lat, lon, int(month))


# ── mémoire journal : mots-clés d'abord, embeddings option ──

def embeddings_enabled() -> bool:
    return (os.environ.get("NAVIGUIDE_EMBEDDINGS") or "").strip() == "1"


def _slim_wx(entry: dict) -> dict[str, Any]:
    return {
        k: entry.get(k)
        for k in (
            "kind", "t", "event", "name", "windKnots", "maxWindKnots",
            "hs", "maxHs", "dirFromDeg", "hours", "level", "model", "basis",
        )
        if entry.get(k) is not None
    }


def _question_threshold(question: str) -> Optional[float]:
    nums: list[float] = []
    for m in _NUM_RE.findall(question or ""):
        try:
            nums.append(float(m.replace(",", ".")))
        except ValueError:
            continue
    return nums[0] if nums else None


def wx_keyword_hits(question: str, entries: list[dict] | None) -> list[dict]:
    """Faits wx déjà au journal. Aucun souvenir inventé.

    « avons-nous déjà eu plus de 35 nœuds ? » → les entrées dont
    `windKnots` / `maxWindKnots` ≥ 35. Sans seuil : les `gale` / `sea`.
    """
    q = question or ""
    thr = _question_threshold(q)
    if thr is None and not _WX_WORDS.search(q):
        return []
    sea_q = bool(_SEA_WORDS.search(q))
    out: list[dict] = []
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        wind = e.get("maxWindKnots") if e.get("maxWindKnots") is not None else e.get("windKnots")
        hs = e.get("maxHs") if e.get("maxHs") is not None else e.get("hs")
        if thr is not None:
            if sea_q:
                if isinstance(hs, (int, float)) and float(hs) >= thr:
                    out.append(_slim_wx(e))
            elif isinstance(wind, (int, float)) and float(wind) >= thr:
                out.append(_slim_wx(e))
        elif e.get("event") in {"gale", "sea"} or e.get("kind") == "wx":
            out.append(_slim_wx(e))
    return out[:8]


def _wx_embed_text(entry: dict) -> str:
    parts = [str(entry.get("kind") or "wx"), str(entry.get("event") or "")]
    for k in ("t", "windKnots", "maxWindKnots", "hs", "maxHs", "hours", "level", "model"):
        if entry.get(k) is not None:
            parts.append(f"{k}={entry[k]}")
    return " ".join(p for p in parts if p)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


async def _embed(texts: list[str], client: httpx.AsyncClient | None) -> list[list[float]]:
    key = nebius_key()
    if not key or not texts:
        return []
    url = f"{TOKENFACTORY_BASE}/embeddings"
    payload = {"model": EMBED_MODEL, "input": texts}
    own = client is None
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=8.0))
    try:
        r = await http.post(
            url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
        )
        if r.status_code >= 400:
            return []
        data = r.json()
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []
        out: list[list[float]] = []
        for row in sorted(rows, key=lambda x: int((x or {}).get("index") or 0)):
            emb = (row or {}).get("embedding")
            if isinstance(emb, list) and emb:
                out.append([float(v) for v in emb])
        return out
    except Exception:
        return []
    finally:
        if own:
            await http.aclose()


async def wx_embed_hits(
    question: str, entries: list[dict] | None, client: httpx.AsyncClient | None = None,
) -> list[dict]:
    """Qwen/Qwen3-Embedding-8B — seulement si NAVIGUIDE_EMBEDDINGS=1. Faits seuls."""
    items = [e for e in (entries or []) if isinstance(e, dict)]
    if not items or not (question or "").strip():
        return []
    vecs = await _embed([question] + [_wx_embed_text(e) for e in items], client)
    if len(vecs) != 1 + len(items):
        return []
    qv, evs = vecs[0], vecs[1:]
    ranked = sorted(
        ((_cosine(qv, ev), e) for e, ev in zip(items, evs)),
        key=lambda p: -p[0],
    )
    return [_slim_wx(e) for score, e in ranked if score >= EMBED_MIN_COS][:5]


async def similar_wx(
    question: str, entries: list[dict] | None, client: httpx.AsyncClient | None = None,
) -> list[dict]:
    """Mots-clés d'abord ; embeddings seulement si le drapeau est à 1 et rien trouvé."""
    hits = wx_keyword_hits(question, entries)
    if hits:
        return hits
    if embeddings_enabled():
        return await wx_embed_hits(question, entries, client)
    return []


# ── answer ──────────────────────────────────────────────────────────────────

def is_hard_question(question: str, parsed: dict | None = None) -> bool:
    """Pourquoi / comment / assez longue (FR et EN). Lightning peut aussi poser intent=reason."""
    q = " ".join((question or "").split())
    if not q:
        return False
    if _WHY_RE.search(q) or _REASON_WORDS.search(q) or _ROUTE_RE.search(q):
        return True
    if len(q) >= FAST_QUESTION_MAX:
        return True
    if isinstance(parsed, dict) and parsed.get("intent") == "reason":
        return True
    return False


def chat_tier(question: str) -> str:
    """Simple → classement (`fast`). Difficile → Ultra (`judge`). Jamais Super (`write`)."""
    return "judge" if is_hard_question(question) else "fast"


def _prompt(question: str, ctx: dict, lang: str) -> tuple[str, str]:
    """Prompt Ultra (question difficile). Les faits simples passent par les règles, pas par write."""
    en = (lang or "fr").lower().startswith("en")
    missing = missing_info("en" if en else "fr")
    system = (
        "You are the logbook of the Berry-Mappemonde sailing expedition. Answer this hard "
        "question in at most FIVE plain sentences, from the facts provided (including the official "
        "logbook in journal — stops, EEZ, protected areas, weather, science, news, polar, "
        "skipper orders, plan review, cables, DC families). "
        "When portWeb.status is ready, you may use its excerpts only — never invent beyond them; they are third-party web news about the port, never about our boat, its arrival or its weather: attribute them ('according to a web source') and never mix their figures with the boat's. "
        "Every figure you write must appear in the facts, with its unit. "
        f"If a fact is missing, say exactly: {missing} "
        "Never mention JSON, field names or keys such as atQuay or speedKnots; "
        "say the fact in words. No title, no list, no bold, nothing about tools or models. Thinking OFF."
        if en else
        "Tu es le journal de bord de l’expédition à la voile Berry-Mappemonde. Réponds à cette "
        "question difficile en CINQ phrases simples au plus, à partir des faits fournis (dont le journal "
        "officiel — escales, ZEE, AMP, météo, science, veilles, polaire, ordres, revue du plan, "
        "câbles, familles DC). Quand portWeb.status vaut ready, tu peux t'appuyer "
        "sur ses extraits seulement — n'invente rien au-delà ; ce sont des nouvelles web de tiers sur le port, jamais sur notre bateau, son arrivée ni sa météo : attribue-les (« selon une source web ») et ne mêle jamais leurs chiffres à ceux du bateau. Chaque chiffre que tu écris doit "
        "figurer dans les faits, avec son unité. "
        f"Si un fait manque, dis exactement : {missing} "
        "N’écris jamais JSON ni les noms de champs "
        "(atQuay, speedKnots…) : dis le fait en mots. Ni titre, ni liste, ni gras, rien sur les outils "
        "ou les modèles. Thinking OFF."
    )
    user = f"{'Question' if en else 'Question'} : {question}\n{'Facts' if en else 'Faits'} :\n{json.dumps(ctx, ensure_ascii=False, default=str)}"
    return system, user


def _parse_prompt(question: str) -> tuple[str, str]:
    system = (
        "Return ONLY a JSON object with keys intent, quantity, place, when, layer. "
        "intent is fact, reason or other. Other keys are strings or null. "
        "No prose, no markdown, Thinking OFF."
    )
    return system, (question or "").strip()


_RAW_LINE_RE = re.compile(
    r"\b(?:formalities|protectedAreas|portsOfEntry|around)\s*:\s*[^\n.]+(?:\.)?",
    re.I,
)
_RAW_FIELD_RE = re.compile(
    r"\(?\b(?:"
    r"atQuay|speedKnots|windKnots|dirFromDeg|filmNm|sailNm|holdHours|"
    r"plannedKnots|remainingNm|fromStop|toStop|seaHours|eventId|stableKey|"
    r"gold_pack|mrgid|zee|amp|poe"
    r")\s*:\s*(?:\([^)]*\)|[^)\n;,(]+(?:,\s*)?)+\)?",
    re.I,
)
# Lightning sometimes leaks `(atQuay false, speed 0.5 knots)` — no colon.
_RAW_PAREN_KEY_RE = re.compile(
    r"\([^)]*\b(?:atQuay|speedKnots|windKnots|dirFromDeg|filmNm|sailNm)\b[^)]*\)",
    re.I,
)
_JSON_EXCUSE_RE = re.compile(
    r"(?:the\s+)?JSON\s+does\s+not\b|JSON\s+ne\s+(?:contient|tient)\b|"
    r"le\s+JSON\s+ne\s+(?:contient|tient)\b",
    re.I,
)


def strip_raw_fields(text: str) -> str:
    """Drop leaked JSON keys such as « (atQuay: true) » or « formalities: zee, amp »."""
    out = _RAW_LINE_RE.sub("", text or "")
    prev = None
    while prev != out:
        prev = out
        out = _RAW_FIELD_RE.sub("", out)
    out = _RAW_PAREN_KEY_RE.sub("", out)
    out = re.sub(r"\(\s*\)", "", out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([,.;])", r"\1", out)
    return out.strip()


def excuse_is_json_missing(text: str) -> bool:
    return bool(_JSON_EXCUSE_RE.search(text or ""))


def _numbers(text: str) -> set[str]:
    out = set()
    for m in _NUM_RE.findall(text or ""):
        try:
            out.add(format(float(m.replace(",", ".")), "g"))  # "03" == "3", "14,2" == "14.2"
        except ValueError:
            continue
    return out


def filter_numbers(answer: str, ctx: dict) -> tuple[str, int]:
    """Drop every sentence carrying a number absent from the context (a year
    or a time in the context counts). Returns (text, dropped)."""
    allowed = _numbers(json.dumps(ctx, ensure_ascii=False, default=str))
    # Dates split into parts: 2026-05-15T08:00 → 2026, 05, 15, 08, 00 are all present already via _NUM_RE.
    kept, dropped = [], 0
    for s in _SENT_SPLIT_RE.split(answer or ""):
        s = s.strip()
        if not s:
            continue
        nums = _numbers(s)
        if nums and not nums.issubset(allowed):
            dropped += 1
            continue
        kept.append(s)
    return " ".join(kept), dropped


def summarize(question: str, answer: str) -> str:
    q = " ".join((question or "").split())[:90]
    first = _SENT_SPLIT_RE.split(answer or "")[0].strip() if answer else ""
    return f"{q} → {first[:160]}".strip(" →")


def _lang_en(lang: str | None) -> bool:
    return str(lang or "fr").lower().startswith("en")


def missing_info(lang: str | None) -> str:
    return _MISSING_EN if _lang_en(lang) else _MISSING_FR


def _fmt_ctx_num(value: Any) -> str | None:
    """Same digits `filter_numbers` will accept — never a written figure."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    return format(float(value), "g")


def _wind_facts(ctx: dict) -> tuple[str | None, str | None]:
    official = ctx.get("official") if isinstance(ctx.get("official"), dict) else {}
    wind = official.get("wind") if isinstance(official.get("wind"), dict) else {}
    return _fmt_ctx_num(wind.get("windKnots")), _fmt_ctx_num(wind.get("dirFromDeg"))


def _speed_facts(ctx: dict) -> tuple[str | None, bool]:
    boat = ctx.get("boat") if isinstance(ctx.get("boat"), dict) else {}
    official = ctx.get("official") if isinstance(ctx.get("official"), dict) else {}
    raw = boat.get("speedKnots")
    if raw is None:
        raw = official.get("speedKnots")
    kn = _fmt_ctx_num(raw)
    at_quay = bool(boat.get("atQuay") or official.get("atQuay"))
    if kn is not None and float(raw) == 0:
        at_quay = True
    return kn, at_quay


def _next_stop_name(ctx: dict) -> str | None:
    stop = ctx.get("nextStop") if isinstance(ctx.get("nextStop"), dict) else None
    if not stop:
        return None
    name = stop.get("name")
    if not name:
        return None
    text = str(name).strip()
    return text or None


def month_from_text(text: str | None) -> int | None:
    folded = _fold(text or "")
    for name, num in _MONTH_NAMES.items():
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", folded):
            return num
    return None


def has_reason_prefix(question: str) -> bool:
    return bool(_REASON_PREFIX_RE.match(question or ""))


def strip_reason_prefix(question: str) -> str:
    return _REASON_PREFIX_RE.sub("", question or "", count=1).strip() or (question or "").strip()


def empty_intent() -> dict[str, Any]:
    return {"intent": "other", "quantity": None, "place": None, "when": None, "layer": None}


def normalize_intent(raw: Any) -> dict[str, Any]:
    out = empty_intent()
    if not isinstance(raw, dict):
        return out
    intent = str(raw.get("intent") or "other").strip().lower()
    out["intent"] = intent if intent in {"fact", "reason", "other"} else "other"
    qty = raw.get("quantity")
    if qty is not None and str(qty).strip():
        key = _fold(str(qty)).strip()
        out["quantity"] = _QTY_ALIASES.get(key, key.replace(" ", "_"))
    for field in ("place", "when", "layer"):
        val = raw.get(field)
        if val is not None and str(val).strip() and str(val).strip().lower() not in {"null", "none"}:
            out[field] = str(val).strip()
    if not out["when"]:
        m = month_from_text(str(raw.get("when") or "") + " " + str(raw.get("quantity") or ""))
        if m:
            out["when"] = str(m)
    return out


def keyword_intent(question: str) -> dict[str, Any]:
    """Analyseur FR/EN : même JSON que Lightning, sans appel réseau."""
    q = question or ""
    folded = _fold(q)
    out = empty_intent()
    q_compact = " ".join(q.split())
    if _REASON_WORDS.search(q) or _WHY_RE.search(q) or len(q_compact) >= FAST_QUESTION_MAX:
        out["intent"] = "reason"
    else:
        out["intent"] = "fact"
    if _POLAR_WORDS.search(q):
        out["quantity"] = "polar"
    elif _ETA_WORDS.search(q):
        out["quantity"] = "eta"
    elif _CLIMO_WORDS.search(q):
        out["quantity"] = "climo"
    elif _SETTING_WORDS.search(q):
        out["quantity"] = "setting"
    elif _DEPTH_WORDS.search(q):
        out["quantity"] = "depth"
    elif _ZEE_WORDS.search(q):
        out["quantity"] = "zee"
    elif _PROJECT_WORDS.search(q):
        out["quantity"] = "projects"
    elif _HEADING_WORDS.search(q):
        out["quantity"] = "heading"
    elif _POSITION_WORDS.search(q):
        out["quantity"] = "position"
    elif _STOP_WORDS.search(q):
        out["quantity"] = "next_stop"
    elif _SPEED_WORDS.search(q):
        out["quantity"] = "speed"
    elif _WX_WORDS.search(q):
        out["quantity"] = "wind"
    if out["quantity"] is None and out["intent"] == "fact":
        out["intent"] = "other"
    m = month_from_text(q)
    if m:
        out["when"] = str(m)
        if out["quantity"] is None:
            out["quantity"] = "climo"
            out["intent"] = "fact"
    # Place: leftover proper names after stripping known words — Madère / Madeira / Ajaccio.
    place = None
    m_at = re.search(
        r"(?i)(?:\bà|\ba|\bat|\bin|\bvers|\bto)\s+([A-ZÀ-Ÿ][\wÀ-ÿ'’\-]+(?:\s+[A-ZÀ-Ÿ][\wÀ-ÿ'’\-]+){0,3})",
        q,
    )
    if m_at:
        place = m_at.group(1).strip()
    if not place:
        for token in re.findall(r"[A-ZÀ-Ÿ][\wÀ-ÿ'’\-]{2,}", q):
            # À-Ÿ includes lowercase é — « prévue » is not a toponym.
            if not token[:1].isupper():
                continue
            folded_tok = _fold(token)
            if folded_tok in _MONTH_NAMES or folded_tok in _PLACE_SKIP:
                continue
            place = token
            break
    if place:
        out["place"] = place
    if re.search(r"(?i)(c[aâ]bles?|bathy|amp|zee)", q):
        out["layer"] = "cables" if re.search(r"(?i)c[aâ]bles?", q) else (
            "bathy" if re.search(r"(?i)bathy|profondeur|depth", q) else (
                "amp" if re.search(r"(?i)\bamp\b", q) else "zee"
            )
        )
        if out["layer"] == "cables" and out["quantity"] is None:
            out["quantity"] = "cables"
            if out["intent"] == "other":
                out["intent"] = "fact"
    return out


def parse_intent_text(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    blob = raw
    m = _JSON_OBJ_RE.search(raw)
    if m:
        blob = m.group(0)
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    parsed = normalize_intent(data)
    if parsed["intent"] == "other" and parsed["quantity"] is None and parsed["place"] is None:
        # Lightning answered but empty — let keywords decide.
        return None
    return parsed


async def understand_question(
    question: str, lang: str, http: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Nano ne rend qu'un JSON d'intention. Sinon mots-clés. Repli : Lightning, puis NIM."""
    fallback = keyword_intent(question)
    try:
        import llm_budget  # noqa: PLC0415
        if not llm_budget.allow("nano"):
            return fallback
    except Exception:
        return fallback
    system, user = _parse_prompt(question)
    try:
        raw, _source = await cascade_text(
            system, user, http, tier="nano", fallback="", max_tokens=PARSE_MAX_TOKENS,
        )
    except Exception:
        return fallback
    parsed = parse_intent_text(raw)
    return parsed or fallback


def _place_match(needle: str | None, name: str | None) -> bool:
    if not needle or not name:
        return False
    a, b = _fold(needle), _fold(name)
    return a in b or b in a


def _eta_named_place(place: str | None) -> str | None:
    """Keep only a real toponym. « Arrivée » / « Expected » are not a stop."""
    if not place:
        return None
    folded = _fold(place)
    if folded in _PLACE_SKIP or folded in _MONTH_NAMES:
        return None
    return str(place).strip() or None


def _leg_for_place(ctx: dict, place: str | None) -> dict | None:
    plan = ctx.get("plan") if isinstance(ctx.get("plan"), dict) else {}
    legs = [lg for lg in (plan.get("legs") or []) if isinstance(lg, dict)]
    if place:
        for lg in legs:
            if _place_match(place, lg.get("to")) or _place_match(place, lg.get("from")):
                return lg
        nxt = _next_stop_name(ctx)
        if nxt and _place_match(place, nxt):
            stop = ctx.get("nextStop") if isinstance(ctx.get("nextStop"), dict) else {}
            return {"to": nxt, "arriveIso": stop.get("eta")}
        return None
    nxt = _next_stop_name(ctx)
    if nxt:
        for lg in legs:
            if _place_match(nxt, lg.get("to")):
                return lg
    return legs[0] if len(legs) == 1 else None


def _fmt_iso_day(iso: str | None) -> str | None:
    if not iso:
        return None
    text = str(iso)
    return text[:10] if len(text) >= 10 else text


def _wind_template(ctx: dict, en: bool) -> str | None:
    kn, deg = _wind_facts(ctx)
    if kn and deg:
        return f"Wind at the boat: {kn} kn, from {deg}°." if en else f"Vent au bateau : {kn} kn, de {deg}°."
    if kn:
        return f"Wind at the boat: {kn} kn." if en else f"Vent au bateau : {kn} kn."
    if deg:
        return f"Wind at the boat: from {deg}°." if en else f"Vent au bateau : de {deg}°."
    mem = ctx.get("memory") if isinstance(ctx.get("memory"), list) else []
    if mem and isinstance(mem[0], dict):
        mkn = _fmt_ctx_num(mem[0].get("maxWindKnots") if mem[0].get("maxWindKnots") is not None else mem[0].get("windKnots"))
        day = _fmt_iso_day(mem[0].get("t"))
        if mkn and day:
            return f"The logbook notes {mkn} kn on {day}." if en else f"Le journal note {mkn} kn le {day}."
        if mkn:
            return f"The logbook notes {mkn} kn." if en else f"Le journal note {mkn} kn."
    return None


def _speed_template(ctx: dict, en: bool) -> str | None:
    kn, at_quay = _speed_facts(ctx)
    if at_quay:
        return "The boat is at the quay." if en else "Le bateau est à quai."
    if kn:
        return f"Speed: {kn} kn." if en else f"Vitesse : {kn} kn."
    return None


def _polar_template(ctx: dict, question: str, en: bool) -> str | None:
    polar = ctx.get("polar") if isinstance(ctx.get("polar"), dict) else {}
    speeds = polar.get("speedAtTws") if isinstance(polar.get("speedAtTws"), dict) else {}
    tws = _question_threshold(question)
    key = None
    if tws is not None:
        # Prefer an exact column (15 not 10 when the skipper said 15).
        as_int = str(int(tws)) if float(tws).is_integer() else None
        as_g = format(float(tws), "g")
        if as_int and as_int in speeds:
            key = as_int
        elif as_g in speeds:
            key = as_g
        else:
            for k in speeds:
                try:
                    if abs(float(k) - float(tws)) < 0.01:
                        key = k
                        break
                except (TypeError, ValueError):
                    continue
    if key is None and "15" in speeds:
        key = "15"
    kn = _fmt_ctx_num(speeds.get(key)) if key is not None else None
    tws_txt = _fmt_ctx_num(float(key)) if key is not None else None
    if kn and tws_txt:
        return (
            f"Polar speed at {tws_txt} kn of wind: {kn} kn."
            if en else
            f"Vitesse polaire par {tws_txt} kn de vent : {kn} kn."
        )
    vmg = polar.get("vmgUpwind") if isinstance(polar.get("vmgUpwind"), dict) else None
    vmg_kn = _fmt_ctx_num((vmg or {}).get("vmgKn")) if vmg else None
    if vmg_kn:
        return (
            f"Best upwind VMG: {vmg_kn} kn."
            if en else
            f"Meilleure VMG au près : {vmg_kn} kn."
        )
    return None


def _eta_template(ctx: dict, place: str | None, en: bool) -> str | None:
    named = _eta_named_place(place)
    lg = _leg_for_place(ctx, named)
    if not lg:
        if named:
            return None
        name = _next_stop_name(ctx)
        stop = ctx.get("nextStop") if isinstance(ctx.get("nextStop"), dict) else {}
        day = _fmt_iso_day(stop.get("eta"))
        if name and day:
            return f"Next stop {name}, arrival {day}." if en else f"Prochaine escale {name}, arrivée {day}."
        if name:
            return f"Next stop: {name}." if en else f"Prochaine escale : {name}."
        return None
    name = lg.get("to") or place
    arrive = _fmt_iso_day(lg.get("arriveIso"))
    p10 = _fmt_iso_day(lg.get("p10"))
    p90 = _fmt_iso_day(lg.get("p90"))
    bits: list[str] = []
    if name and arrive:
        bits.append(f"Arrival at {name}: {arrive}." if en else f"Arrivée à {name} : {arrive}.")
    elif name:
        bits.append(f"Stop: {name}." if en else f"Escale : {name}.")
    if p10 and p90:
        bits.append(f"Window {p10} – {p90}." if en else f"Fourchette {p10} – {p90}.")
    return " ".join(bits) if bits else None


def _setting_template(ctx: dict, question: str, en: bool) -> str | None:
    orders = ctx.get("orders") if isinstance(ctx.get("orders"), dict) else {}
    q = _fold(question)
    if "confort" in q or "comfort" in q:
        comfort = orders.get("comfort")
        if comfort:
            return f"Comfort setting: {comfort}." if en else f"Réglage de confort : {comfort}."
    knobs = orders.get("knobs") if isinstance(orders.get("knobs"), dict) else {}
    if "horizon" in q and knobs.get("horizonH") is not None:
        h = _fmt_ctx_num(knobs.get("horizonH"))
        if h:
            return f"Horizon: {h} h." if en else f"Horizon : {h} h."
    values = orders.get("values") if isinstance(orders.get("values"), dict) else {}
    for key, val in values.items():
        if _fold(key) in q and val is not None:
            num = _fmt_ctx_num(val)
            if num:
                return f"{key}: {num}." if en else f"{key} : {num}."
    profile = orders.get("profile")
    if profile and ("profil" in q or "profile" in q):
        return f"Profile: {profile}." if en else f"Profil : {profile}."
    comfort = orders.get("comfort")
    if comfort:
        return f"Comfort setting: {comfort}." if en else f"Réglage de confort : {comfort}."
    return None


def _climo_template(ctx: dict, en: bool) -> str | None:
    climo = ctx.get("climo") if isinstance(ctx.get("climo"), dict) else {}
    month = climo.get("month")
    kn = _fmt_ctx_num(climo.get("windMeanKn"))
    gust = _fmt_ctx_num(climo.get("gustKn"))
    hs = _fmt_ctx_num(climo.get("hsM") if climo.get("hsM") is not None else climo.get("hsP90M"))
    bits: list[str] = []
    if kn:
        if month:
            bits.append(
                f"Climatology for month {month}: mean wind {kn} kn."
                if en else
                f"Climatologie du mois {month} : vent moyen {kn} kn."
            )
        else:
            bits.append(f"Mean wind {kn} kn." if en else f"Vent moyen {kn} kn.")
    if gust:
        bits.append(f"Gusts {gust} kn." if en else f"Rafales {gust} kn.")
    if hs:
        bits.append(f"Swell {hs} m." if en else f"Houle {hs} m.")
    return " ".join(bits) if bits else None


def _depth_template(ctx: dict, en: bool) -> str | None:
    around = ctx.get("around") if isinstance(ctx.get("around"), dict) else {}
    layers = ctx.get("layers") if isinstance(ctx.get("layers"), dict) else {}
    depth = layers.get("bathyM") if layers.get("bathyM") is not None else around.get("depthM")
    kn = _fmt_ctx_num(depth)
    if kn:
        return f"Depth: {kn} m." if en else f"Profondeur : {kn} m."
    return None


def _zee_template(ctx: dict, en: bool) -> str | None:
    around = ctx.get("around") if isinstance(ctx.get("around"), dict) else {}
    zee = around.get("zee") if isinstance(around.get("zee"), dict) else None
    if not zee:
        layers = ctx.get("layers") if isinstance(ctx.get("layers"), dict) else {}
        zee = layers.get("zee") if isinstance(layers.get("zee"), dict) else None
    name = (zee or {}).get("name") if zee else None
    if name:
        return f"EEZ: {name}." if en else f"ZEE : {name}."
    return None


def _projects_template(ctx: dict, en: bool) -> str | None:
    around = ctx.get("around") if isinstance(ctx.get("around"), dict) else {}
    items = [it for it in (around.get("projects") or []) if isinstance(it, dict) and it.get("name")]
    if not items:
        return None
    names = ", ".join(str(it["name"]) for it in items[:3])
    first_nm = _fmt_ctx_num(items[0].get("nm"))
    if first_nm:
        return (
            f"Nearby projects: {names} ({first_nm} nm)."
            if en else
            f"Projets proches : {names} ({first_nm} nm)."
        )
    return f"Nearby projects: {names}." if en else f"Projets proches : {names}."


def _position_template(ctx: dict, en: bool) -> str | None:
    boat = ctx.get("boat") if isinstance(ctx.get("boat"), dict) else {}
    official = ctx.get("official") if isinstance(ctx.get("official"), dict) else {}
    lat = _fmt_ctx_num(boat.get("lat") if boat.get("lat") is not None else official.get("lat"))
    lon = _fmt_ctx_num(boat.get("lon") if boat.get("lon") is not None else official.get("lon"))
    if lat and lon:
        return f"Boat position: {lat}, {lon}." if en else f"Position du bateau : {lat}, {lon}."
    return None


def _heading_template(ctx: dict, en: bool) -> str | None:
    boat = ctx.get("boat") if isinstance(ctx.get("boat"), dict) else {}
    official = ctx.get("official") if isinstance(ctx.get("official"), dict) else {}
    hdg = boat.get("headingDeg") if boat.get("headingDeg") is not None else official.get("headingDeg")
    kn = _fmt_ctx_num(hdg)
    if kn:
        return f"Heading: {kn}°." if en else f"Cap : {kn}°."
    return None


def _next_stop_template(ctx: dict, en: bool) -> str | None:
    name = _next_stop_name(ctx)
    if name:
        return f"Next stop: {name}." if en else f"Prochaine escale : {name}."
    return None


def _cable_template(ctx: dict, en: bool) -> str | None:
    families = ctx.get("dcFamilies") if isinstance(ctx.get("dcFamilies"), list) else []
    cable_row = next((r for r in families if isinstance(r, dict) and r.get("kind") == "cable"), None)
    if cable_row and cable_row.get("name"):
        return f"Cable: {cable_row['name']}." if en else f"Câble : {cable_row['name']}."
    layers = ctx.get("layers") if isinstance(ctx.get("layers"), dict) else {}
    cables = layers.get("cables") if isinstance(layers.get("cables"), dict) else None
    if cables and cables.get("nearby") is True:
        return "A submarine cable passes here." if en else "Un câble sous-marin passe ici."
    if cables and cables.get("nearby") is False:
        return "No submarine cable at this point." if en else "Aucun câble sous-marin au point."
    return None


def _dc_family_template(ctx: dict, kind: str, en: bool) -> str | None:
    families = ctx.get("dcFamilies") if isinstance(ctx.get("dcFamilies"), list) else []
    row = next((r for r in families if isinstance(r, dict) and r.get("kind") == kind), None)
    if not row:
        return None
    name = row.get("name")
    nm = _fmt_ctx_num(row.get("nm"))
    if kind == "depth":
        depth = _fmt_ctx_num(row.get("depthM"))
        if depth:
            return f"Depth: {depth} m." if en else f"Profondeur : {depth} m."
    if name and nm:
        return f"{name} ({nm} nm)." if en else f"{name} ({nm} nm)."
    if name:
        return f"{name}."
    if row.get("phrase"):
        return str(row["phrase"])
    return None


def rules_answer(
    question: str,
    ctx: dict | None,
    lang: str | None,
    parsed: dict | None = None,
) -> str:
    """Gabarit FR/EN par grandeur. Chaque nombre est copié du paquet. Aucun chiffre rédigé."""
    if not isinstance(ctx, dict):
        return missing_info(lang)
    en = _lang_en(lang)
    q = question or ""
    parsed = parsed or keyword_intent(q)
    qty = parsed.get("quantity") if isinstance(parsed, dict) else None
    place = parsed.get("place") if isinstance(parsed, dict) else None
    templates: dict[str, Any] = {
        "wind": lambda: _wind_template(ctx, en),
        "speed": lambda: _speed_template(ctx, en),
        "heading": lambda: _heading_template(ctx, en),
        "eta": lambda: _eta_template(ctx, place, en),
        "depth": lambda: _depth_template(ctx, en),
        "next_stop": lambda: _next_stop_template(ctx, en),
        "zee": lambda: _zee_template(ctx, en),
        "projects": lambda: _projects_template(ctx, en),
        "climo": lambda: _climo_template(ctx, en),
        "setting": lambda: _setting_template(ctx, q, en),
        "polar": lambda: _polar_template(ctx, q, en),
        "position": lambda: _position_template(ctx, en),
        "cables": lambda: _cable_template(ctx, en) or _dc_family_template(ctx, "cable", en),
        "layer": lambda: _cable_template(ctx, en) or _depth_template(ctx, en) or _zee_template(ctx, en),
    }
    if qty in templates:
        text = templates[qty]()
        return text or missing_info(lang)
    # Sans grandeur : uniquement si la question la nomme. Pas un vent collé
    # sur « prix du gasoil ». Pour un raisonnement, le fait le plus proche ensuite.
    parts: list[str] = []
    if _WX_WORDS.search(q):
        bit = _wind_template(ctx, en)
        if bit:
            parts.append(bit)
    if not parts and _SPEED_WORDS.search(q):
        bit = _speed_template(ctx, en)
        if bit:
            parts.append(bit)
    if not parts and _STOP_WORDS.search(q):
        bit = _next_stop_template(ctx, en)
        if bit:
            parts.append(bit)
    if not parts and isinstance(parsed, dict) and parsed.get("intent") == "reason":
        for key in ("wind", "speed", "next_stop", "eta", "polar", "climo", "setting"):
            bit = templates[key]()
            if bit:
                parts.append(bit)
                break
    return " ".join(parts) if parts else missing_info(lang)


def _finish_answer(raw: str, ctx: dict, lang: str, source: str, *, sentences: int, chars: int) -> dict[str, Any]:
    tidy = tidy_story(raw, None, max_sentences=sentences, max_chars=chars)
    text, dropped = filter_numbers(tidy, ctx)
    text = strip_raw_fields(_clean_text(text))
    if not text or excuse_is_json_missing(text):
        text = missing_info(lang)
        source = "rules"
    return enrich_llm_payload({
        "status": "ready",
        "answer": text,
        "engine": source,
        "source": source,
        "droppedSentences": dropped,
        "context": ctx,
    })


async def answer_question(
    question: str,
    lang: str,
    client_ctx: dict | None,
    now: datetime,
    http: httpx.AsyncClient | None = None,
    reason: bool = False,
) -> dict[str, Any]:
    q = strip_reason_prefix(question)
    ctx = await build_context(client_ctx, now, http, question=q)
    from toponyms import localize_ctx_places  # noqa: PLC0415
    localize_ctx_places(ctx, lang)
    try:
        import voyage_journal as journal  # noqa: PLC0415
        wx_all = journal.latest(WX_MEMORY, kinds=("wx",))
    except Exception:
        wx_all = [e for e in (ctx.get("journal") or []) if isinstance(e, dict) and e.get("kind") == "wx"]
    memory = await similar_wx(q, wx_all, http)
    if memory:
        ctx["memory"] = memory
    parsed = await understand_question(q, lang, http)
    month = None
    if parsed.get("when"):
        try:
            month = int(str(parsed["when"]).strip())
        except (TypeError, ValueError):
            month = month_from_text(str(parsed.get("when")))
    if month:
        apply_climo_month(ctx, month)
    try:
        fact_text = rules_answer(q, ctx, lang, parsed)
    except Exception:
        fact_text = None

    hard = bool(reason) or has_reason_prefix(question) or is_hard_question(q, parsed)
    if hard:
        import llm_budget  # noqa: PLC0415
        if llm_budget.allow("judge"):
            system, user = _prompt(q, ctx, lang)
            fallback = fact_text if fact_text is not None else missing_info(lang)
            try:
                raw, source = await cascade_text(
                    system, user, http, tier="judge", fallback=fallback, facts=ctx,
                )
            except Exception as exc:
                if fact_text is None:
                    return {
                        "status": "failed",
                        "reason": str(exc)[:160],
                        "answer": None,
                        "engine": None,
                        "source": None,
                        "context": ctx,
                    }
                raw, source = fact_text, "rules"
            out = _finish_answer(raw, ctx, lang, source, sentences=ULTRA_SENTENCES, chars=ULTRA_CHARS)
            if out.get("source") == "nemotron-ultra":
                llm_budget.record_chat_ultra()
            return out
        if fact_text is None:
            return {
                "status": "failed",
                "reason": "unreadable",
                "answer": None,
                "engine": None,
                "source": None,
                "context": ctx,
            }
        return _finish_answer(fact_text, ctx, lang, "rules", sentences=ANSWER_SENTENCES, chars=ANSWER_CHARS)

    if fact_text is None:
        return {
            "status": "failed",
            "reason": "unreadable",
            "answer": None,
            "engine": None,
            "source": None,
            "context": ctx,
        }
    return _finish_answer(fact_text, ctx, lang, "rules", sentences=ANSWER_SENTENCES, chars=ANSWER_CHARS)


# ── endpoint ────────────────────────────────────────────────────────────────

class ChatIn(BaseModel):
    question: str
    lang: Optional[str] = "fr"
    context: Optional[dict] = None
    reason: Optional[bool] = False


_chat_limited = rate_limited("logbook-chat", 6, 60.0, global_limit=60)


def _facts_view(ctx: dict | None) -> dict[str, Any]:
    ctx = ctx if isinstance(ctx, dict) else {}
    keys = ("official", "boat", "nextStop", "memory", "journal", "polar", "orders", "plan", "climo", "layers", "dcFamilies", "around")
    return {k: ctx.get(k) for k in keys if ctx.get(k) is not None}


# Paquet /logbook/facts de l'heure UTC (la position du bateau change dans la journée).
# Le chat (POST) recalcule ; seul ce GET est mis en cache.
_FACTS_CACHE: dict[str, dict] = {}
_FACTS_LOCKS: dict[str, asyncio.Lock] = {}


def reset_facts_cache() -> None:
    _FACTS_CACHE.clear()
    _FACTS_LOCKS.clear()


def facts_cache_key(now: datetime, lang: str | None) -> str:
    """Heure UTC + langue + fonction de contexte (un monkeypatch de test ne réutilise pas la prod)."""
    day = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H")
    return f"{day}|{(lang or 'fr')[:2]}|{id(build_context)}"


@router.get("/logbook/facts", dependencies=[Depends(_chat_limited)])
async def get_logbook_facts(request: Request, lang: Optional[str] = "fr"):
    """Paquet de faits du chat (recette RG19). Même limite que POST /logbook/chat.

    Le premier appel du jour paie le calcul (~18 s à froid). Le suivant, le même
    jour et la même langue, relit le paquet.
    """
    now = datetime.now(timezone.utc)
    key = facts_cache_key(now, lang)
    hit = _FACTS_CACHE.get(key)
    if hit is not None:
        return {**hit, "cached": True}
    lock = _FACTS_LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _FACTS_CACHE.get(key)
        if hit is not None:
            return {**hit, "cached": True}
        ctx = await build_context(None, now)
        from toponyms import localize_ctx_places  # noqa: PLC0415
        localize_ctx_places(ctx, lang or "fr")
        body = {
            "status": "ready",
            "t": now.isoformat().replace("+00:00", "Z"),
            "tokens": estimate_tokens(ctx),
            "facts": ctx,
            "cached": False,
        }
        _FACTS_CACHE[key] = body
        return body


@router.post("/logbook/chat", dependencies=[Depends(_chat_limited)])
async def post_logbook_chat(body: ChatIn, request: Request):
    """Une question au journal de bord ; consignée (kind chat) quand la clé admin est là."""
    q = " ".join((body.question or "").split())
    if not q:
        raise HTTPException(400, "question vide")
    if len(q) > QUESTION_MAX:
        raise HTTPException(413, f"question trop longue (> {QUESTION_MAX} caractères)")
    if body.context is not None and len(json.dumps(body.context, default=str)) > CONTEXT_MAX_BYTES:
        raise HTTPException(413, "contexte trop volumineux")
    now = datetime.now(timezone.utc)
    out = await answer_question(
        q, body.lang or "fr", body.context, now, reason=bool(body.reason),
    )
    logged = False
    entry = None
    if out["status"] == "ready" and is_admin(request):
        import voyage_journal as journal  # noqa: PLC0415
        try:
            entry = journal.add_chat(q, out["answer"], summarize(q, out["answer"]), now, lang=body.lang or "fr", engine=out.get("engine"))
            logged = True
        except Exception as exc:  # the journal never breaks an answer
            log.warning("journal chat : %s", exc)
    import port_web_context  # noqa: PLC0415

    pw_ctx = out.get("context") if isinstance(out.get("context"), dict) else None
    web_sources = port_web_context.web_sources_for_response(pw_ctx)
    pw = pw_ctx.get("portWeb") if pw_ctx else None
    return enrich_llm_payload({
        "status": out["status"],
        "answer": out.get("answer"),
        "reason": out.get("reason"),
        "engine": out.get("engine"),
        "source": out.get("source") or out.get("engine"),
        "logged": logged,
        "entry": entry,
        "t": now.isoformat().replace("+00:00", "Z"),
        "facts": _facts_view(out.get("context")),
        "webSources": web_sources,
        "portWebStatus": pw.get("status") if isinstance(pw, dict) else None,
    })
