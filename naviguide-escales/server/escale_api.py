"""Fiche d'escale (plan général §1.9).

Pour une escale (nom, position) : ce qu'un équipage veut savoir en arrivant,
**en listes de faits** — chaque ligne a un nom, une position, une distance,
et quand OSM / BI le disent un site et un téléphone :

- amarrage : marinas, capitaineries (BI), ports WPI, mouillages OSM ;
- services : carburant, eau potable, électricité à quai (OSM) ;
- avitaillement : supermarchés, épiceries, laveries (OSM) ;
- entretien : chantiers, grues, cales de mise à l'eau, accastillage (OSM) ;
- tourisme : sites, musées, points de vue, offices de tourisme (OSM) ;
- formalités : ZEE, ports d'entrée officiels (BI), aires marines protégées ;
- autour : projets et fiches science Blue Intelligence.

La **rédaction** (un paragraphe de présentation, trois phrases) passe par
`cascade_text(tier="fast")` à partir de ces listes seulement,
filtrée comme les cartes ; sans LLM, les listes seules. Rien n'est inventé :
une section vide n'est pas envoyée. Cache par escale, sans le jour dans la
clé (`pearl_store.kv`, ns « escale », TTL 7 j) : la fiche survit au
changement de jour UTC jusqu'à `ESCALE_TTL_S`. Le cache mémoire, lui, est
indexé par escale et par jour UTC (`_day_mem_key`) si le store n'a pas la fiche. Le chauffeur de perles n'est
pas lancé ici. Chaque paragraphe porte `source`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from admin_guard import rate_limited, require_admin
from ici_engine import fill_dossier, haversine_nm
from ici_layers import _overpass_elements, _overpass_latlon
from ai_transparency import with_ai_transparency
from story_cascade import _clean_text, cascade_text, tidy_story, translate

log = logging.getLogger("naviguide-simulator.escale")

router = APIRouter()

ESCALE_TTL_S = 7 * 86400.0
ESCALE_CACHE_REV = "tf3"
_NIM_SOURCE_RE = re.compile(r"nvidia|gpt-oss|\bnim\b", re.I)
OSM_RADIUS_M = 6000          # ~3.2 nm around the stop: the town, not the coast
BAG_RADIUS_NM = 15.0
MAX_PER_SECTION = 6
PARAGRAPH_SENTENCES = 3
PARAGRAPH_CHARS = 520

# tag → (section, subsection)
_OSM_TAGS: tuple[tuple[str, str, str, str], ...] = (
    ("amenity", "fuel", "services", "fuel"),
    ("waterway", "fuel", "services", "fuel"),
    ("seamark:small_craft_facility:category", "fuel", "services", "fuel"),
    ("amenity", "drinking_water", "services", "water"),
    ("seamark:small_craft_facility:category", "water", "services", "water"),
    ("seamark:small_craft_facility:category", "electricity", "services", "electricity"),
    ("shop", "supermarket", "supplies", "supermarkets"),
    ("shop", "convenience", "supplies", "supermarkets"),
    ("shop", "laundry", "supplies", "laundry"),
    ("shop", "boat", "maintenance", "chandlery"),
    ("shop", "chandler", "maintenance", "chandlery"),
    ("shop", "chandlery", "maintenance", "chandlery"),
    ("waterway", "boatyard", "maintenance", "boatyards"),
    ("seamark:small_craft_facility:category", "boatyard", "maintenance", "boatyards"),
    ("man_made", "crane", "maintenance", "cranes"),
    ("seamark:small_craft_facility:category", "boat_hoist", "maintenance", "cranes"),
    ("leisure", "slipway", "maintenance", "slipways"),
    ("seamark:small_craft_facility:category", "slipway", "maintenance", "slipways"),
    ("tourism", "attraction", "tourism", "sights"),
    ("tourism", "museum", "tourism", "museums"),
    ("tourism", "viewpoint", "tourism", "viewpoints"),
    ("tourism", "information", "tourism", "information"),
    ("amenity", "pharmacy", "health", "pharmacies"),
    ("amenity", "hospital", "health", "hospitals"),
)

SECTION_ORDER = ("mooring", "services", "supplies", "maintenance", "tourism", "health", "formalities", "around")


def osm_query(lat: float, lon: float, radius_m: int = OSM_RADIUS_M) -> str:
    around = f"(around:{int(radius_m)},{lat:.5f},{lon:.5f})"
    seen = set()
    parts = []
    for k, v, _s, _sub in _OSM_TAGS:
        if (k, v) in seen:
            continue
        seen.add((k, v))
        parts.append(f'nwr["{k}"="{v}"]{around};')
    return f"[out:json][timeout:25];({''.join(parts)});out center tags;"


def _website(tags: dict) -> str | None:
    for k in ("website", "contact:website", "url", "seamark:information"):
        v = tags.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v[:300]
    return None


def _phone(tags: dict) -> str | None:
    for k in ("phone", "contact:phone", "seamark:contact:phone"):
        v = tags.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:40]
    return None


def classify_osm(elements: list, lat0: float, lon0: float) -> dict[str, dict[str, list[dict]]]:
    """Overpass elements → { section: { subsection: [items] } }, nearest first, capped."""
    out: dict[str, dict[str, list[dict]]] = {}
    seen: set[tuple] = set()
    for el in elements or []:
        tags = el.get("tags") or {}
        pos = _overpass_latlon(el)
        if pos is None:
            continue
        lat, lon = pos
        for k, v, section, sub in _OSM_TAGS:
            if tags.get(k) != v:
                continue
            name = tags.get("name") or tags.get("brand") or tags.get("operator")
            if not name and section in ("tourism", "supplies", "health"):
                continue  # an unnamed shop tells nothing
            label = str(name or v.replace("_", " "))[:120]
            key = (section, sub, round(lat, 4), round(lon, 4), label)
            if key in seen:
                continue
            seen.add(key)
            item = {
                "name": label,
                "lat": round(lat, 5),
                "lon": round(lon, 5),
                "nm": round(haversine_nm(lat0, lon0, lat, lon), 2),
                "source": "osm-overpass",
            }
            url = _website(tags)
            if url:
                item["url"] = url
            phone = _phone(tags)
            if phone:
                item["phone"] = phone
            if tags.get("opening_hours"):
                item["hours"] = str(tags["opening_hours"])[:80]
            if section == "services" and sub == "fuel":
                kinds = [f for f in ("diesel", "gasoline") if tags.get(f"fuel:{f}") == "yes"]
                if kinds:
                    item["fuel"] = kinds
            out.setdefault(section, {}).setdefault(sub, []).append(item)
            break
    for section in out.values():
        for sub, items in section.items():
            items.sort(key=lambda x: x["nm"])
            # Named places first; anonymous taps / cranes / slipways: the two nearest only.
            named = [i for i in items if i["name"] not in {v.replace("_", " ") for _k, v, _s, _sub in _OSM_TAGS}]
            anon = [i for i in items if i not in named][:2]
            items[:] = sorted(named + anon, key=lambda x: x["nm"])[:MAX_PER_SECTION]
    return out


def _slim(items: list | None, keep: tuple[str, ...] = ("name", "lat", "lon", "nm", "url", "visit_url", "manager_url", "gold_on", "phone", "type", "kind", "source", "enrich", "phrase")) -> list[dict]:
    out = []
    for it in items or []:
        if not isinstance(it, dict) or not it.get("name"):
            continue
        out.append({k: it[k] for k in keep if k in it and it[k] is not None})
    return out[:MAX_PER_SECTION]


def sections_from_bag(bag: dict) -> dict[str, Any]:
    nearby = bag.get("nearby") or {}
    sections: dict[str, Any] = {}
    mooring = {
        "marinas": _slim(nearby.get("marinas")),
        "capitaineries": _slim(nearby.get("capitaineries")),
        "wpi": _slim(nearby.get("wpi")),
        "anchorages": _slim(nearby.get("anchorages")),
    }
    mooring = {k: v for k, v in mooring.items() if v}
    if mooring:
        sections["mooring"] = mooring
    zee = bag.get("zee") or {}
    formalities = {
        "zee": {k: zee.get(k) for k in ("name", "mrgid", "territory", "gold", "country") if zee.get(k) is not None} if zee else None,
        "poe": _slim(bag.get("poe")),
        "amp": _slim(bag.get("amp")),
    }
    formalities = {k: v for k, v in formalities.items() if v}
    if formalities:
        sections["formalities"] = formalities
    science = bag.get("science")
    around = {
        "projects": _slim(bag.get("projects")),
        "science": _slim(science.get("nearby") if isinstance(science, dict) else science),
    }
    around = {k: v for k, v in around.items() if v}
    if around:
        sections["around"] = around
    return sections


def merge_sections(base: dict, osm: dict) -> dict:
    merged = {k: dict(v) if isinstance(v, dict) else v for k, v in base.items()}
    for section, subs in osm.items():
        merged.setdefault(section, {})
        for sub, items in subs.items():
            if items:
                merged[section][sub] = items
    return {k: merged[k] for k in SECTION_ORDER if k in merged and merged[k]}


def _paragraph_prompt(name: str, sections: dict, lang: str) -> tuple[str, str]:
    en = (lang or "fr").lower().startswith("en")
    system = (
        "You present a port of call to a sailing crew arriving there, from JSON lists already collected "
        "(marinas, harbour master, fuel, water, shops, boatyards, sights, port of entry, protected areas). "
        "THREE plain sentences at most: what is there for the boat, what is there for the crew, what to know "
        "for formalities. Name only places present in the JSON, never a figure not in it. "
        "No title, no list, no bold, nothing about the machinery or the data sources. Thinking OFF."
        if en else
        "Tu présentes une escale à un équipage de voilier qui y arrive, à partir de listes JSON déjà collectées "
        "(marinas, capitainerie, carburant, eau, commerces, chantiers, sites, port d’entrée, aires protégées). "
        "TROIS phrases simples au plus : ce qu’il y a pour le bateau, ce qu’il y a pour l’équipage, ce qu’il faut "
        "savoir pour les formalités. Ne nomme que des lieux présents dans le JSON, jamais un chiffre absent. "
        "Ni titre, ni liste, ni gras, rien sur la machinerie ni sur les sources. Thinking OFF."
    )
    slim = {}
    for section, subs in sections.items():
        slim[section] = {}
        for sub, items in subs.items():
            if isinstance(items, list):
                slim[section][sub] = [{k: it.get(k) for k in ("name", "nm") if it.get(k) is not None} for it in items[:4]]
            else:
                slim[section][sub] = items
    user = f"{'Port of call' if en else 'Escale'} : {name}\nJSON :\n{json.dumps(slim, ensure_ascii=False, default=str)}"
    return system, user


@with_ai_transparency
async def write_paragraph(name: str, sections: dict, lang: str, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    if not sections:
        return {"status": "empty", "text": None, "engine": None, "source": None}
    # Rédiger en FR, puis traduire si le client demande EN.
    system, user = _paragraph_prompt(name, sections, "fr")
    try:
        text, source = await cascade_text(system, user, client, tier="fast")
    except Exception as exc:
        return {"status": "failed", "text": None, "engine": None, "source": None, "reason": str(exc)[:160]}
    tidy = tidy_story(text, None, max_sentences=PARAGRAPH_SENTENCES, max_chars=PARAGRAPH_CHARS)
    if not tidy:
        return {"status": "failed", "text": None, "engine": source, "source": source, "reason": "only machinery"}
    if str(lang or "fr").lower().startswith("en"):
        tidy, source = await translate(tidy, "en", client, facts=tidy)
        if not tidy:
            return {"status": "failed", "text": None, "engine": source, "source": source, "reason": "empty translation"}
    tidy = _clean_text(tidy)
    if not tidy:
        return {"status": "failed", "text": None, "engine": source, "source": source, "reason": "prompt leak"}
    from logbook_chat import strip_raw_fields  # noqa: PLC0415
    tidy = strip_raw_fields(tidy)
    if not tidy:
        return {"status": "failed", "text": None, "engine": source, "source": source, "reason": "prompt leak"}
    return {"status": "ready", "text": tidy, "engine": source, "source": source}


def escale_day_token() -> str:
    """Jour UTC : ne clefe que le cache mémoire de secours, pas la fiche (gardée ESCALE_TTL_S)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def escale_key(name: str, lat: float, lon: float, lang: str) -> str:
    """Sans le jour : la fiche et son paragraphe LLM payant restent ESCALE_TTL_S (7 j)."""
    return (
        f"{name.strip().lower()[:60]}|{lat:.2f}|{lon:.2f}|{(lang or 'fr')[:2]}"
        f"|{ESCALE_CACHE_REV}"
    )


# Fiche du jour déjà calculée, si SQLite n'a pas répondu. Pas le chauffeur de perles.
_DAY_MEM: dict[str, dict] = {}


def _day_mem_key(key: str) -> str:
    return f"{key}|{escale_day_token()}"
_BUILDING: dict[str, asyncio.Task] = {}
_build_thread = threading.Lock()


def reset_escale_hot_cache() -> None:
    _DAY_MEM.clear()
    _BUILDING.clear()


async def _build_escale_once(key: str, name: str, lat: float, lon: float, lang: str) -> dict:
    """Un seul calcul à froid par clé du jour, même si plusieurs onglets ouvrent la fiche."""
    with _build_thread:
        task = _BUILDING.get(key)
        if task is None or task.done():
            task = asyncio.create_task(build_escale(name, lat, lon, lang))
            _BUILDING[key] = task
    try:
        return await task
    finally:
        with _build_thread:
            if task.done() and _BUILDING.get(key) is task:
                _BUILDING.pop(key, None)


def _remember_escale(key: str, fiche: dict) -> None:
    if isinstance(fiche, dict) and fiche.get("sections") and not nim_paragraph(fiche):
        _DAY_MEM[_day_mem_key(key)] = fiche


def _forget_escale(key: str) -> None:
    _DAY_MEM.pop(_day_mem_key(key), None)


def nim_paragraph(fiche: dict | None) -> bool:
    src = str(((fiche or {}).get("paragraph") or {}).get("source") or "")
    return bool(_NIM_SOURCE_RE.search(src))


def _sanitize_item_text(item: dict) -> dict:
    """Drop leaked model-thinking from a list row (enrich / phrase)."""
    out = dict(item)
    raw = out.get("phrase")
    if isinstance(raw, str) and raw.strip():
        cleaned = _clean_text(raw)
        if cleaned:
            out["phrase"] = cleaned
        else:
            out.pop("phrase", None)
    enrich = out.get("enrich")
    if isinstance(enrich, dict) and isinstance(enrich.get("text"), str) and enrich["text"].strip():
        cleaned = _clean_text(enrich["text"])
        if cleaned:
            out["enrich"] = {**enrich, "text": cleaned}
        else:
            rest = {k: v for k, v in enrich.items() if k != "text"}
            if rest.get("url"):
                out["enrich"] = rest
            else:
                out.pop("enrich", None)
    return out


def _sanitize_sections(sections: dict) -> dict:
    clean: dict = {}
    for section, subs in sections.items():
        if not isinstance(subs, dict):
            clean[section] = subs
            continue
        new_subs: dict = {}
        for sub, items in subs.items():
            if isinstance(items, list):
                new_subs[sub] = [
                    _sanitize_item_text(it) if isinstance(it, dict) else it for it in items
                ]
            else:
                new_subs[sub] = items
        clean[section] = new_subs
    return clean


def sanitize_fiche(val: dict) -> dict | None:
    """Strip leaked LLM text. None = the paragraph itself is a leak (rebuild)."""
    if not isinstance(val, dict):
        return val
    out = dict(val)
    para = out.get("paragraph")
    if isinstance(para, dict) and isinstance(para.get("text"), str) and para["text"].strip():
        from logbook_chat import strip_raw_fields  # noqa: PLC0415
        cleaned = strip_raw_fields(_clean_text(para["text"]))
        if not cleaned:
            return None
        out["paragraph"] = {**para, "text": cleaned}
    if isinstance(out.get("sections"), dict):
        out["sections"] = _sanitize_sections(out["sections"])
    return out


_TOURISM_SUBS = ("sights", "museums", "viewpoints")


def tourism_highlights_from_cache(
    name: str,
    lat: float | None,
    lon: float | None,
    lang: str = "fr",
    limit: int = 2,
) -> list[dict]:
    """Deux lieux remarquables de la section tourisme, si la fiche est en cache.

    Lecture seule — pas de réseau. Champ inconnu = liste vide, jamais inventé.
    """
    if not name or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return []
    try:
        import pearl_store  # noqa: PLC0415
    except Exception:
        return []
    langs = [(lang or "fr")[:2]]
    other = "en" if langs[0] == "fr" else "fr"
    if other not in langs:
        langs.append(other)
    hit = None
    for lg in langs:
        hit = pearl_store.kv_get("escale", escale_key(name, float(lat), float(lon), lg), ESCALE_TTL_S)
        if hit:
            break
    if not hit:
        return []
    tourism = ((hit.get("value") or {}).get("sections") or {}).get("tourism") or {}
    if not isinstance(tourism, dict):
        return []
    items: list[dict] = []
    for sub in _TOURISM_SUBS:
        for it in tourism.get(sub) or []:
            if isinstance(it, dict) and it.get("name"):
                items.append({**it, "subsection": sub})
    items.sort(key=lambda x: (not isinstance(x.get("nm"), (int, float)), x.get("nm") or 0))
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        label = str(it["name"]).strip()
        if not label or label in seen:
            continue
        seen.add(label)
        row = {"name": label, "kind": it.get("subsection")}
        for k in ("lat", "lon", "nm", "url"):
            if it.get(k) is not None:
                row[k] = it[k]
        out.append(row)
        if len(out) >= limit:
            break
    return out


async def build_escale(name: str, lat: float, lon: float, lang: str = "fr",
                       client: httpx.AsyncClient | None = None, *, paragraph: bool = True) -> dict[str, Any]:
    own = client is None
    http = client or httpx.AsyncClient()
    try:
        bag_t = asyncio.create_task(fill_dossier(lat, lon, BAG_RADIUS_NM, client=http, thin=True, rich=False))
        osm_t = asyncio.create_task(_overpass_elements(http, osm_query(lat, lon)))
        bag, (elements, osm_err) = await asyncio.gather(bag_t, osm_t)
        sections = merge_sections(sections_from_bag(bag), classify_osm(elements, lat, lon))
        para = await write_paragraph(name, sections, lang, http) if paragraph else {"status": "disabled", "text": None, "engine": None, "source": None}
        return {
            "name": name,
            "lat": lat,
            "lon": lon,
            "lang": lang,
            "sections": sections,
            "paragraph": para,
            "sources": {
                "osm": "osm-overpass" if not osm_err else osm_err,
                "bi": (bag.get("sources") or {}).get("bi"),
                "zee": (bag.get("sources") or {}).get("zee"),
            },
            "builtAt": time.time(),
        }
    finally:
        if own:
            await http.aclose()


_escale_limited = rate_limited("escale", 20, 60.0, global_limit=120)
_INFLIGHT: set[str] = set()
# Référence forte : une tâche asyncio sans référence peut être ramassée en cours de route.
_WATCH_TASKS: set[Any] = set()


def _watch_task_done(task: Any, key: str) -> None:
    """Lit l'exception de la tâche (pas de « never retrieved ») et libère le slug en cas d'échec."""
    _WATCH_TASKS.discard(task)
    if task.cancelled():
        _INFLIGHT.discard(key)
        return
    exc = task.exception()
    if exc is not None:
        _INFLIGHT.discard(key)
        log.warning("veille %s : %s", key, exc)


def _schedule_escale_watch(name: str, lat: float, lon: float) -> None:
    """Une veille en tâche de fond si l'escale officielle est dans la fenêtre.

    La réponse HTTP ne l'attend pas. Un slug déjà lancé n'est pas relancé.
    """
    try:
        import escale_watch  # noqa: PLC0415
        import llm_budget  # noqa: PLC0415
    except Exception:
        return
    if not escale_watch.watch_enabled():
        return
    try:
        stop = escale_watch.official_stop_in_window(name, lat=lat, lon=lon)
    except Exception as exc:
        log.debug("fenêtre veille : %s", exc)
        return
    if not stop:
        return
    key = str(stop.get("slug") or escale_watch.slug(name))
    if escale_watch.watch_done(key) or not llm_budget.allow_tavily():
        return
    if key in _INFLIGHT:
        return
    _INFLIGHT.add(key)
    try:
        task = asyncio.create_task(escale_watch.watch_stop(stop, datetime.now(timezone.utc)))
        _WATCH_TASKS.add(task)
        task.add_done_callback(lambda t, k=key: _watch_task_done(t, k))
    except RuntimeError:
        _INFLIGHT.discard(key)
        log.debug("veille non planifiée : %s", key)


@router.get("/escale/watch/settings")
async def get_watch_settings():
    """R42 : état de la veille Tavily (interrupteur des réglages) et défaut du poste."""
    import escale_watch  # noqa: PLC0415
    return escale_watch.watch_settings()


@router.post("/escale/watch/settings", dependencies=[Depends(require_admin)])
async def post_watch_settings(body: dict[str, Any]):
    """R42 : allume ou coupe la veille Tavily côté serveur (gardé dans pearl_store)."""
    import escale_watch  # noqa: PLC0415
    enabled = (body or {}).get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise HTTPException(400, "enabled (booléen ou null) requis")
    escale_watch.set_watch_override(enabled)
    try:
        import ici_warm  # noqa: PLC0415
        if escale_watch.watch_enabled():
            ici_warm.ensure_watch_loop()
        else:
            ici_warm.cancel_watch_loop()
    except Exception as exc:
        log.debug("boucle veille : %s", exc)
    return escale_watch.watch_settings()


@router.get("/escale", dependencies=[Depends(_escale_limited)])
async def get_escale(
    name: str = Query(..., min_length=1, max_length=120),
    lat: float = Query(...),
    lon: float = Query(...),
    lang: str = Query("fr"),
    refresh: bool = Query(False),
):
    """La fiche d'une escale : listes de faits + un paragraphe (cascade LLM), en cache 7 j."""
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(400, "lat/lon hors limites")
    _schedule_escale_watch(name, lat, lon)
    import pearl_store  # noqa: PLC0415
    key = escale_key(name, lat, lon, lang)
    if not refresh:
        hit = pearl_store.kv_get("escale", key, ESCALE_TTL_S)
        if hit:
            val = hit.get("value") if isinstance(hit, dict) else None
            sanitized = sanitize_fiche(val) if isinstance(val, dict) else None
            if sanitized is None:
                pearl_store.kv_delete("escale", key)
                _forget_escale(key)
                hit = None
            elif sanitized:
                if nim_paragraph(sanitized):
                    pearl_store.kv_delete("escale", key)
                    _forget_escale(key)
                    hit = None
                else:
                    if sanitized != val:
                        pearl_store.kv_put("escale", key, sanitized)
                    _remember_escale(key, sanitized)
                    return {**sanitized, "cached": True}
        remembered = _DAY_MEM.get(_day_mem_key(key))
        if isinstance(remembered, dict) and not nim_paragraph(remembered):
            return {**remembered, "cached": True}
    else:
        _forget_escale(key)
        # A refresh also re-collects the stop's own pearl (its ZEE, its layers).
        from ici_engine import thin_cache_drop, thin_cache_key  # noqa: PLC0415
        thin_cache_drop(thin_cache_key(lat, lon, BAG_RADIUS_NM))
    fiche = await _build_escale_once(key, name, lat, lon, lang)
    sanitized = sanitize_fiche(fiche)
    if sanitized is None:
        para = dict(fiche.get("paragraph") or {})
        fiche = {
            **fiche,
            "paragraph": {
                **para,
                "status": "failed",
                "text": None,
                "reason": "prompt leak",
                "source": para.get("source") or "rules",
            },
        }
        sanitized = sanitize_fiche(fiche) or fiche
    # Only a fiche with something in it is worth keeping; a failed paragraph
    # is retried on the next request that finds the cache stale.
    if sanitized.get("sections"):
        pearl_store.kv_put("escale", key, sanitized)
        _remember_escale(key, sanitized)
    return {**sanitized, "cached": False}
