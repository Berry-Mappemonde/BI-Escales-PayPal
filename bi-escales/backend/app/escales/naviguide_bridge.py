"""Read-only bridge: NAVIGUIDE escale export → BI milestone rows.

When ``ESCALES_NAVIGUIDE_ENABLED`` is off, ``local_schedule_export`` is used
(no HTTP, no partner). The bridge never writes to NAVIGUIDE.

The local rows are the stopovers of ``frontend/public/route.geojson``,
with the same ids as ``milestoneIdFromName`` and the hour offsets of
``voyageClock.js`` at ``2026-11-12T08:00:00.000Z`` (``route_schedule.json``).
``clock_start()`` shifts those offsets, so the dates follow the 12 November
2026 clock instead of a fixed August/September pair.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any, Optional

import httpx

from ..escales_names import display_name
from .config import clock_start, naviguide_api_base, naviguide_bridge_enabled, naviguide_json_path

_ROUTE_SCHEDULE_PATH = Path(__file__).with_name("route_schedule.json")
# Same civil time as voyageClock.DEFAULT_T0_ISO (08:00Z on the clock date).
_CLOCK_AT = dt.time(8, 0, tzinfo=dt.timezone.utc)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_FOLD = str.maketrans("àâäáéèêëíìîïóòôöúùûüçñ", "aaaaeeeeiiiioooouuuucn")


def _slug(name: str) -> str:
    folded = (name or "").strip().lower().translate(_FOLD)
    return _SLUG_RE.sub("-", folded).strip("-") or "escale"

# Heures de la jambe terrestre Saint-Maur → La Rochelle.
# naviguide-escales/server/voyage_clock.py LAND_CALENDAR_HOURS
# naviguide-escales/src/engine/voyageClock.js SAINT_MAUR_LAND_HOURS
_LAND_HOURS = 4.0


def _route_stops() -> list[dict[str, Any]]:
    payload = json.loads(_ROUTE_SCHEDULE_PATH.read_text(encoding="utf-8"))
    rows = payload.get("escales") or []
    return [row for row in rows if isinstance(row, dict)]


def _arrival_iso(t_hours: Any, slug: str = "") -> str:
    """Arrival on the voyage clock. ``t_hours`` is the offset from 08:00Z.

    Saint-Maur stays at the clock origin. Every later stop, including La
    Rochelle, adds the 4 h land budget so the first leg is not zero-length.
    """
    try:
        hours = float(t_hours or 0)
    except (TypeError, ValueError):
        hours = 0.0
    if slug != "saint-maur-berry-indre":
        hours += _LAND_HOURS
    base = dt.datetime.combine(dt.date.fromisoformat(clock_start()), _CLOCK_AT)
    moment = base + dt.timedelta(hours=hours)
    return moment.replace(microsecond=0).isoformat()


def local_schedule_export() -> dict[str, Any]:
    """Fallback schedule when the NAVIGUIDE bridge is disabled.

    Ids and order come from the route. Dates are ``clock_start()`` plus the
    clock offset, so a 12 November 2026 departure keeps Fort-de-France before
    Mayotte and both after that day.
    """
    escales: list[dict[str, Any]] = []
    for item in _route_stops():
        milestone_id = str(item.get("milestone_id") or "").strip()
        if not milestone_id:
            continue
        escales.append(
            {
                "milestone_id": milestone_id,
                "name": item.get("name") or milestone_id,
                "slug": item.get("slug") or milestone_id.removeprefix("dep-"),
                "lat": item.get("lat"),
                "lon": item.get("lon"),
                "arrival_iso": _arrival_iso(item.get("t_hours"), str(item.get("slug") or "")),
                "flag": True,
            }
        )
    return {
        "version": 1,
        "provider": "local",
        "clock_start": clock_start(),
        "escales": escales,
    }


def escales_to_milestones(export: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn an export payload into milestone-shaped dicts (no ledger write)."""
    rows: list[dict[str, Any]] = []
    for item in export.get("escales") or []:
        if not isinstance(item, dict):
            continue
        milestone_id = str(item.get("milestone_id") or "").strip()
        named = str(item.get("name") or "").strip()
        if not milestone_id:
            if not named:
                continue
            milestone_id = f"dep-{_slug(named)}"
        shown = named or display_name(str(item.get("slug") or milestone_id))
        rows.append(
            {
                "_id": milestone_id,
                "title": item.get("name") or shown,
                "display_name": shown,
                "arrival_iso": item.get("arrival_iso"),
                "lat": item.get("lat"),
                "lon": item.get("lon"),
                "slug": item.get("slug"),
                "source": export.get("provider") or "NAVIGUIDE",
            }
        )
    return rows


def parse_export(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("export must be a JSON object")
    if "escales" not in raw:
        raise ValueError("export missing escales")
    return raw


def load_export_from_path(path: str) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    return parse_export(json.loads(text))


async def fetch_naviguide_export(client: Optional[httpx.AsyncClient] = None) -> dict[str, Any]:
    """Load escales from a JSON file or NAVIGUIDE ``/escales/export``."""
    if not naviguide_bridge_enabled():
        return local_schedule_export()
    json_path = naviguide_json_path()
    if json_path:
        return load_export_from_path(json_path)
    url = f"{naviguide_api_base()}/escales/export"
    own = client is None
    http = client or httpx.AsyncClient()
    try:
        response = await http.get(url, timeout=15.0)
        response.raise_for_status()
        return parse_export(response.json())
    except Exception:
        return local_schedule_export()
    finally:
        if own:
            await http.aclose()


# Heures figées depuis l'horloge NAVIGUIDE au 12 novembre 2026, 08:00 UTC.
# Sources : voyageClock.js (buildVoyageClock), berryLegs.js (buildBerryLegs),
# routePlayhead.js, escales.js, geo.js, public/route.geojson.
# Une autre date d'horloge décale ces heures sans relancer le vent.
_CABIN_LEGS_PATH = Path(__file__).with_name("cabin_legs.json")
_LEG_TABLE: Optional[dict[str, Any]] = None


def cabin_leg_table() -> dict[str, Any]:
    """Table des jambes. Le fichier cite les pièces NAVIGUIDE dont il est tiré."""
    global _LEG_TABLE
    if _LEG_TABLE is None:
        _LEG_TABLE = json.loads(_CABIN_LEGS_PATH.read_text(encoding="utf-8"))
    return _LEG_TABLE


def _clock_origin():
    """08:00 UTC le jour de ``clock_start``. Même heure que le t0 de l'horloge."""
    import datetime as dt

    from .config import clock_start

    return dt.datetime.fromisoformat(f"{clock_start()}T08:00:00+00:00")


def _reference_t0():
    import datetime as dt

    raw = str(cabin_leg_table().get("t0") or "2026-11-12T08:00:00.000Z")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    moment = dt.datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment


def _shift_iso(raw: Any) -> str:
    """Date de la table, décalée si l'horloge de développement n'est pas le 12 novembre."""
    import datetime as dt

    text = str(raw or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = dt.datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    shifted = moment + (_clock_origin() - _reference_t0())
    return shifted.replace(microsecond=0).isoformat()


def _plus_hours(raw: str, hours: float) -> str:
    moment = dt.datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return (moment + dt.timedelta(hours=hours)).replace(microsecond=0).isoformat()


def clock_legs() -> list[dict[str, Any]]:
    """Une jambe par paire d'escales, datée par l'horloge du 12 novembre 2026.

    ``departure_iso`` est le départ de A (arrivée + séjour au quai).
    ``arrival_iso`` est l'arrivée en B. La capture d'une cabine suit le départ.
    La table figée met Saint-Maur et La Rochelle à la même heure. Le budget
    terrestre de 4 h (``LAND_CALENDAR_HOURS``) sépare les deux, et la mer
    part quand La Rochelle est atteinte.
    """
    rows: list[dict[str, Any]] = []
    for item in cabin_leg_table().get("legs") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        row = dict(item)
        row["milestone_id"] = item["id"]
        departure = _shift_iso(item.get("departure_iso"))
        arrival = _shift_iso(item.get("arrival_iso"))
        if item["id"] == "leg-saint-maur-berry-indre-to-la-rochelle":
            arrival = _plus_hours(departure, _LAND_HOURS)
        else:
            departure = _plus_hours(departure, _LAND_HOURS)
            arrival = _plus_hours(arrival, _LAND_HOURS)
        row["departure_iso"] = departure
        row["arrival_iso"] = arrival
        row["capture_on"] = "departure"
        rows.append(row)
    return rows


def leg_by_id(leg_id: str) -> Optional[dict[str, Any]]:
    wanted = (leg_id or "").strip()
    if not wanted:
        return None
    for leg in clock_legs():
        if leg["id"] == wanted:
            return leg
    return None


def leg_departing_from(place: str) -> Optional[dict[str, Any]]:
    """Première jambe qui quitte cette escale, dans l'ordre de l'horloge."""
    slug = _slug(place)
    if slug.startswith("dep-"):
        slug = slug[4:]
    if len(slug) < 4:
        return None
    needle = f"-{slug}-"
    for leg in clock_legs():
        hay = f"-{leg.get('from_slug')}-"
        if needle in hay or hay.strip("-") == slug:
            return leg
    return None


def _bare_port(value: str) -> str:
    text = (value or "").strip()
    for prefix in ("dep-", "ret-"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text


def _leg_links(leg: dict[str, Any], origin: str, dest: str) -> bool:
    """True when the leg runs from ``origin`` to ``dest``, return stop included.

    ``La Rochelle`` and ``ret-la-rochelle`` are the same port on arrival.
    """
    return _bare_port(str(leg.get("from_slug") or "")) == _bare_port(origin) and (
        _bare_port(str(leg.get("to_slug") or "")) == _bare_port(dest)
    )


_DIRECTION_STOP = {
    "vers", "depuis", "from", "to", "toward", "jusqu", "jusqua", "return", "retour", "the", "a",
}


def _place_fragment(fragment: str) -> Optional[str]:
    """First place in a direction phrase. Later ports stay out of the match."""
    words: list[str] = []
    for word in re.split(r"\s+", (fragment or "").strip(" .,;:")):
        if not word:
            continue
        token = _slug(word)
        if token in _DIRECTION_STOP:
            break
        words.append(word)
        if len(words) == 4:
            break
    for size in range(len(words), 0, -1):
        chunk = " ".join(words[:size])
        found = resolve_milestone(chunk)
        if not found or str(found).startswith("leg-"):
            continue
        head = resolve_milestone(words[0])
        if head and head != found and size > 1:
            continue
        return found
    return None


_FROM_CUE = re.compile(
    r"\b(?:depuis|from|return\s+from|retour\s+d['’]|retour\s+de)\s*"
    r"([A-Za-zÀ-ÿ][^.,;]{0,48})",
    re.IGNORECASE,
)
_TO_CUE = re.compile(
    r"\b(?:vers|jusqu['’]à|jusqu['’]a|to|toward)\s+([A-Za-zÀ-ÿ][^.,;]{0,48})",
    re.IGNORECASE,
)
_RETURN_WORD = re.compile(r"\b(?:retour|return)\b", re.IGNORECASE)


def leg_for_message(message: str) -> Optional[dict[str, Any]]:
    """Pick a cabin leg from direction, not from the first port named.

    ``depuis`` / ``from`` / ``retour de`` name the departure. ``vers`` names
    the arrival. ``retour`` prefers the leg that comes home (Europa →
    ``ret-la-rochelle``) over the outbound La Rochelle → Ajaccio leg.
    """
    text = message or ""
    origin_match = _FROM_CUE.search(text)
    origin = _place_fragment(origin_match.group(1)) if origin_match else None
    dest_match = _TO_CUE.search(text)
    dest = _place_fragment(dest_match.group(1)) if dest_match else None
    if origin and dest:
        for leg in clock_legs():
            if _leg_links(leg, origin, dest):
                return leg
    if origin:
        departed = leg_departing_from(origin)
        if departed:
            return departed
    if not _RETURN_WORD.search(text):
        return None
    mentioned: list[str] = []
    words = re.findall(r"[A-Za-zÀ-ÿ0-9'’\-]+", text)
    for size in (3, 2, 1):
        for index in range(0, max(0, len(words) - size + 1)):
            found = resolve_milestone(" ".join(words[index:index + size]))
            if found and found not in mentioned and not str(found).startswith("leg-"):
                mentioned.append(found)
    homeward = [
        leg for leg in clock_legs()
        if str(leg.get("to_slug") or "").startswith("ret-")
        and any(_bare_port(str(leg.get("from_slug") or "")) == _bare_port(place) for place in mentioned)
    ]
    if len(homeward) == 1:
        return homeward[0]
    return None


# Chat names that are not the route slug. The canonical id stays ``dep-<slug>``.
_CHAT_ALIASES = {
    "mayotte": "dzaoudzi-mayotte",
    "dzaoudzi": "dzaoudzi-mayotte",
    "fort-de-france": "fort-de-france-martinique",
    "martinique": "fort-de-france-martinique",
    "pointe-a-pitre": "pointe-a-pitre-guadeloupe",
    "guadeloupe": "pointe-a-pitre-guadeloupe",
    "la-reunion": "saint-gilles-la-reunion",
    "reunion": "saint-gilles-la-reunion",
    "saint-barthelemy": "gustavia-saint-barthelemy",
    "saint-martin": "marigot-saint-martin",
    "guyane": "cayenne-guyane",
    "polynesie-francaise": "papeete-polynesie-francaise",
    "nouvelle-caledonie": "noumea-nouvelle-caledonie",
    "caledonie": "noumea-nouvelle-caledonie",
    "noumea": "noumea-nouvelle-caledonie",
    "saint-pierre-et-miquelon": "saint-pierre-saint-pierre-et-miquelon",
    "miquelon": "saint-pierre-saint-pierre-et-miquelon",
    "corse": "ajaccio-corse",
    "ajaccio": "ajaccio-corse",
}
# Ports kept by the captain display table, absent from route.geojson.
_EXTRA_STOPS = {
    "dakar": "Dakar",
    "lorient": "Lorient",
    "brest": "Brest",
}


def _bare_slug(token: str) -> str:
    slug = _slug(token)
    if slug.startswith("dep-"):
        slug = slug[4:]
    return slug


def _slug_covers(key: str, slug: str) -> bool:
    """``mayotte`` matches ``dzaoudzi-mayotte``; ``fort-de-france`` matches the island id."""
    if not key or not slug or len(slug) < 4:
        return False
    return key == slug or key.endswith("-" + slug) or key.startswith(slug + "-")


def _schedule_index() -> dict[str, str]:
    """Slug or milestone id → canonical id (``dep-…``, ``ret-…``)."""
    index: dict[str, str] = {}
    for item in local_schedule_export().get("escales") or []:
        if not isinstance(item, dict):
            continue
        milestone_id = str(item.get("milestone_id") or "").strip()
        if not milestone_id:
            continue
        index[milestone_id] = milestone_id
        slug = str(item.get("slug") or "").strip()
        if slug:
            index[slug] = milestone_id
        named = _slug(str(item.get("name") or ""))
        if named:
            index.setdefault(named, milestone_id)
    return index


def resolve_milestone(token: str) -> Optional[str]:
    """One map from a chat slug, a port name, or a leg id to the canonical id.

    Stopovers are ``dep-<slug>`` (``mayotte`` → ``dep-dzaoudzi-mayotte``).
    The return to La Rochelle is ``ret-la-rochelle``. A leg id is returned
    as stored. Unknown text is ``None``.
    """
    raw = (token or "").strip()
    if not raw:
        return None
    index = _schedule_index()
    bare = _bare_slug(raw)
    if raw in index:
        return index[raw]
    if bare in index:
        return index[bare]
    alias = _CHAT_ALIASES.get(bare)
    if alias and alias in index:
        return index[alias]
    if bare in _EXTRA_STOPS:
        return f"dep-{bare}"
    for leg in clock_legs():
        leg_id = str(leg.get("id") or "")
        if leg_id and leg_id in {raw, bare}:
            return leg_id
    partials: list[str] = []
    for key, milestone_id in index.items():
        if key == bare or _slug_covers(key, bare):
            if milestone_id not in partials:
                partials.append(milestone_id)
    if len(partials) == 1:
        return partials[0]
    # A phrase: the longest schedule key or alias that sits inside the text.
    compact = re.sub(r"[^a-z0-9]+", "", bare)
    if compact:
        best_key = ""
        best_id: Optional[str] = None
        pool = list(index.items()) + [(alias, index[target]) for alias, target in _CHAT_ALIASES.items() if target in index]
        pool.extend((slug, f"dep-{slug}") for slug in _EXTRA_STOPS)
        for key, milestone_id in pool:
            folded = re.sub(r"[^a-z0-9]+", "", key)
            if folded and folded in compact and len(folded) > len(best_key):
                best_key = folded
                best_id = milestone_id
        if best_id:
            return best_id
    return None


def leg_milestone_meta(leg: dict[str, Any]) -> dict[str, Any]:
    """Champs du jalon de jambe. La capture lit ``departure_iso``."""
    title = f"{leg.get('from_name')} → {leg.get('to_name')}"
    return {
        "title": title,
        "display_name": title,
        "arrival_iso": leg.get("arrival_iso"),
        "departure_iso": leg.get("departure_iso"),
        "from": leg.get("from_slug"),
        "to": leg.get("to_slug"),
        "from_name": leg.get("from_name"),
        "to_name": leg.get("to_name"),
        "leg_kind": leg.get("kind"),
        "capture_on": "departure",
        "source": "clock",
    }


def legs_to_milestones(legs: Optional[list[dict[str, Any]]] = None) -> list[dict[str, Any]]:
    """Même forme que ``escales_to_milestones``, une ligne par jambe."""
    rows: list[dict[str, Any]] = []
    for leg in legs if legs is not None else clock_legs():
        meta = leg_milestone_meta(leg)
        rows.append(
            {
                "_id": leg["id"],
                "lat": None,
                "lon": None,
                "slug": leg["id"],
                **meta,
            }
        )
    return rows


async def sync_milestone_shells(export: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """Ensure milestone documents exist for each exported escale (meta only)."""
    from .pledges import get_ledger

    payload = export if export is not None else await fetch_naviguide_export()
    rows = escales_to_milestones(payload)
    ledger = get_ledger()
    synced: list[dict[str, Any]] = []
    for row in rows:
        doc = await ledger.ensure_milestone(
            row["_id"],
            meta={
                "title": row.get("title"),
                "display_name": row.get("display_name"),
                "arrival_iso": row.get("arrival_iso"),
                "lat": row.get("lat"),
                "lon": row.get("lon"),
                "source": row.get("source"),
            },
        )
        synced.append(doc)
    return synced


async def sync_leg_shells() -> list[dict[str, Any]]:
    """Un jalon par jambe. La capture suit ``departure_iso``, pas l'arrivée."""
    from .pledges import get_ledger

    ledger = get_ledger()
    synced: list[dict[str, Any]] = []
    for row in legs_to_milestones():
        meta = {key: value for key, value in row.items() if key not in {"_id", "slug", "lat", "lon"}}
        doc = await ledger.ensure_milestone(row["_id"], meta=meta)
        synced.append(doc)
    return synced
