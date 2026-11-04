"""Veille Tavily par escale (U10 / TV1) + enrichissement science / projet (U12).

Liste pré-écrite (avis, travaux, fermeture), nom du port et date
substitués. Au plus deux tours par escale : Lightning lit le 1er, et s'il
manque une réponse il choisit une question de la même liste — il n'en
invente pas. Une phrase, une URL, `filter_numbers`. Prochaines escales
seulement (fenêtre J-10 → J+2). Active par défaut (`NAVIGUIDE_TAVILY_WATCH=1`), coupée par l'interrupteur « Veille Tavily » ;
`NAVIGUIDE_TAVILY_WATCH=0` la coupe. Jamais d'appel depuis le navigateur.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx

import llm_budget
import tavily_client
from story_cascade import cascade_text, filter_numbers
from voyage_clock import parse_iso, to_iso

log = logging.getLogger("naviguide-simulator.watch")

WATCH_NS = "watch"
ENRICH_NS = "enrich"
WATCH_BEFORE_DAYS = 10
WATCH_AFTER_DAYS = 2
WATCH_EXPIRE_DAYS = 2
SEARCH_DAYS = 7
SEARCH_MAX = 5
ENRICH_DAILY_CAP = 8
MAX_EXTRACT_CHARS = 8_000
# Trois questions déjà écrites. Lightning ne peut en choisir qu'une
# parmi celles qui restent. Pas un troisième tour. Pas une moisson.
WATCH_QUESTION_IDS = ("avis", "travaux", "fermeture")
WATCH_QUESTION_TEMPLATES: dict[str, str] = {
    "avis": "{port} avis aux navigateurs {date}",
    "travaux": "{port} travaux port marina {date}",
    "fermeture": "{port} fermeture port {date}",
}
MAX_WATCH_ROUNDS = 2
MAX_WATCH_SEARCHES_PER_STOP = 2
# 3 prochaines escales × 2 tours. Noté dans la PR.
MAX_WATCH_SEARCHES_PER_DAY = 6
# Même id que film_script.TV1_WATCH_ID — pas d'import croisé au chargement.
WATCH_FILM_ID = "dc:watch"

WATCH_SYSTEM = (
    "Tu résumes une veille portuaire en UNE phrase. "
    "Aucun chiffre qui n'est pas déjà dans les extraits. "
    "Pas d'invention. Thinking OFF."
)
ROUND2_SYSTEM = (
    "Lot TV1. Tu lis des extraits Tavily d'escale. "
    "Si une phrase d'avis, de travaux ou de fermeture est déjà possible, "
    'réponds {"question": null}. '
    "S'il manque une réponse, choisis UN id dans remaining "
    '(JSON {"question": "travaux"}). Jamais d\'id hors liste. '
    "Jamais de question inventée. Thinking OFF."
)
ENRICH_SYSTEM = (
    "Tu extraits UNE phrase factuelle sur cette station ou ce projet, "
    "d'après l'extrait officiel seulement. "
    "Aucun chiffre qui n'est pas déjà dans l'extrait. "
    "Pas d'invention. Thinking OFF."
)

# Domaines officiels connus (ports du voyage Berry). Sinon : pas de filtre.
_KNOWN_DOMAINS: dict[str, tuple[str, ...]] = {
    "noumea": ("noumea.nc", "portautonome.nc"),
    "nouméa": ("noumea.nc", "portautonome.nc"),
    "la rochelle": ("portlarochelle.com", "douane.gouv.fr"),
    "fort-de-france": ("douane.gouv.fr", "martinique.gouv.fr"),
    "ajaccio": ("douane.gouv.fr", "corse.gouv.fr"),
    "brisbane": ("msq.qld.gov.au",),
    "san francisco": ("sfport.com",),
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_FOLD = str.maketrans("àâäáéèêëíìîïóòôöúùûüçñ", "aaaaeeeeiiiioooouuuucn")


def slug(name: str) -> str:
    folded = (name or "").strip().lower().translate(_FOLD)
    return _SLUG_RE.sub("-", folded).strip("-") or "escale"


WATCH_SETTINGS_NS = "watch_settings"
_WATCH_SETTINGS_KEY = "enabled"
_WATCH_SETTINGS_UNAVAILABLE = object()
_TRUE = ("1", "true", "yes", "on")


def watch_env_default() -> bool:
    """Défaut du poste : `NAVIGUIDE_TAVILY_WATCH`, active si absent (U0 / PR #159)."""
    return (os.environ.get("NAVIGUIDE_TAVILY_WATCH") or "1").strip().lower() in _TRUE


def watch_override() -> bool | None | object:
    """Choix fait dans l'interrupteur « Veille Tavily » (R42), gardé dans pearl_store.

    None : aucun choix, le défaut du poste s'applique. Une erreur de stockage
    renvoie un marqueur distinct afin que le réglage ne puisse pas se rallumer.
    """
    try:
        hit = _cache_get(WATCH_SETTINGS_NS, _WATCH_SETTINGS_KEY)
    except Exception as exc:  # store illisible : fail closed
        log.debug("réglage veille illisible : %s", exc)
        return _WATCH_SETTINGS_UNAVAILABLE
    val = (hit or {}).get("enabled")
    return val if isinstance(val, bool) else None


def set_watch_override(enabled: bool | None) -> None:
    _cache_put(WATCH_SETTINGS_NS, _WATCH_SETTINGS_KEY, {"enabled": enabled, "at": to_iso(datetime.now(timezone.utc))})


def watch_settings() -> dict[str, Any]:
    override = watch_override()
    default = watch_env_default()
    if override is _WATCH_SETTINGS_UNAVAILABLE:
        return {"enabled": False, "default": default, "source": "error"}
    return {
        "enabled": default if override is None else override,
        "default": default,
        "source": "env" if override is None else "setting",
    }


def watch_enabled() -> bool:
    """Retourne le choix persistant, ou le défaut `NAVIGUIDE_TAVILY_WATCH` (1 par défaut).

    L'interrupteur « Veille Tavily » (R42) l'emporte sur cette variable.
    """
    return bool(watch_settings()["enabled"])


def watch_daily_search_cap() -> int:
    raw = (os.environ.get("NAVIGUIDE_WATCH_DAILY_SEARCHES") or "").strip()
    if not raw:
        return MAX_WATCH_SEARCHES_PER_DAY
    try:
        return max(0, int(raw))
    except ValueError:
        return MAX_WATCH_SEARCHES_PER_DAY


def _question_date(when: datetime | None) -> str:
    return _day(_utc(when))


def format_watch_question(
    qid: str,
    port: str,
    when: datetime | None = None,
) -> str | None:
    """None si l'id n'est pas dans la liste — Lightning n'invente pas."""
    template = WATCH_QUESTION_TEMPLATES.get(str(qid or "").strip())
    if not template:
        return None
    name = (port or "").strip() or "port"
    return template.format(port=name, date=_question_date(when))


def watch_query(port: str, qid: str = "avis", when: datetime | None = None) -> str:
    """Première question de la liste (avis), nom et date substitués."""
    return format_watch_question(qid, port, when) or format_watch_question(
        "avis", port, when,
    ) or ""


def parse_second_question(text: str, remaining: Iterable[str]) -> str | None:
    """JSON {question: id}. Id hors remaining → None (refusée, pas inventée)."""
    left = {str(q) for q in remaining if str(q) in WATCH_QUESTION_IDS}
    if not left:
        return None
    raw = (text or "").strip()
    data: Any = None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                data = None
    token = ""
    if isinstance(data, dict):
        token = str(data.get("question") or data.get("id") or "").strip()
    elif raw:
        token = raw.split()[0].strip('.,;:"\'').strip()
    if token in left:
        return token
    return None


def _has_answer(results: list[Any]) -> bool:
    for item in results:
        if not isinstance(item, dict):
            continue
        raw = item.get("content") or item.get("title") or ""
        if isinstance(raw, str) and raw.strip():
            return True
        url = item.get("url")
        if isinstance(url, str) and url.startswith("http"):
            return True
    return False


def _watch_search_count(day: str | None = None) -> int:
    hit = _cache_get(WATCH_NS, f"day-search:{day or _day(_utc())}")
    try:
        return int((hit or {}).get("n") or 0)
    except (TypeError, ValueError):
        return 0


def _watch_search_inc(day: str | None = None) -> None:
    d = day or _day(_utc())
    _cache_put(WATCH_NS, f"day-search:{d}", {"n": _watch_search_count(d) + 1})


def set_watch_in_film(on: bool) -> None:
    """VS1 a gardé l'id et la phrase est entrée dans le script → pas le chat."""
    _cache_put(WATCH_NS, "in-film", {"on": bool(on)})


def watch_in_film() -> bool:
    hit = _cache_get(WATCH_NS, "in-film")
    return bool(isinstance(hit, dict) and hit.get("on"))


def drop_news_if_in_film(entries: Iterable[Any]) -> list[Any]:
    """Pas la même phrase dans le film et dans le chat."""
    rows = list(entries or [])
    if not watch_in_film():
        return rows
    return [
        e for e in rows
        if not (isinstance(e, dict) and e.get("kind") == "news")
    ]


def latest_watch_entry(now: datetime | None = None) -> dict[str, Any] | None:
    """Phrase d'avis pour le sac VS1 / la fiche : dernière veille encore lisible."""
    when = _utc(now)
    for entry in reversed(_index_get("all")):
        if not isinstance(entry, dict) or expired(entry, when):
            continue
        if str(entry.get("text") or "").strip():
            return entry
    return None


def official_domains(name: str, urls: Iterable[str] | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    key = (name or "").strip().lower()
    for host in _KNOWN_DOMAINS.get(key, ()):
        if host not in seen:
            seen.add(host)
            out.append(host)
    for raw in urls or []:
        host = _host_of(raw)
        if host and host not in seen:
            seen.add(host)
            out.append(host)
    return out


def _host_of(url: str | None) -> str | None:
    raw = (url or "").strip()
    if not raw.startswith("http://") and not raw.startswith("https://"):
        return None
    try:
        host = (urlparse(raw).hostname or "").lower()
    except Exception:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _utc(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _day(now: datetime) -> str:
    return _utc(now).strftime("%Y-%m-%d")


def _day_start(now: datetime) -> datetime:
    t = _utc(now)
    return t.replace(hour=0, minute=0, second=0, microsecond=0)


def expires_at(now: datetime) -> datetime:
    """Fin exclusive de J+2 (visible le jour J, J+1 et J+2) — J = le jour donné.

    Une veille faite une fois par escale expire par rapport à l'ARRIVÉE à
    l'escale (`news_entry` passe `stop["arrival"]`), pas au jour de la recherche :
    cherchée à J-10, elle reste lisible jusqu'à deux jours après l'arrivée."""
    return _day_start(now) + timedelta(days=WATCH_EXPIRE_DAYS + 1)


def expired(entry: dict[str, Any] | None, now: datetime | None = None) -> bool:
    if not entry:
        return True
    raw = entry.get("expires")
    if not raw:
        try:
            t = parse_iso(entry.get("t") or "")
        except Exception:
            return False
        return _utc(now) >= expires_at(t)
    try:
        return _utc(now) >= parse_iso(str(raw))
    except Exception:
        return False


def _arrival(clock: dict[str, Any], mark: dict[str, Any]) -> datetime | None:
    if mark.get("iso"):
        try:
            return parse_iso(mark["iso"])
        except Exception:
            pass
    if mark.get("tHours") is None:
        return None
    try:
        return parse_iso(clock["t0"]) + timedelta(hours=float(mark["tHours"]))
    except Exception:
        return None


def stops_in_window(
    clock: dict[str, Any] | None,
    now: datetime,
    *,
    before_days: int = WATCH_BEFORE_DAYS,
    after_days: int = WATCH_AFTER_DAYS,
) -> list[dict[str, Any]]:
    """Escales dont l'arrivée est dans [now − after ; now + before] wait:

    Fenêtre produit : de J-10 (10 j avant l'arrivée) à J+2 (2 j après).
    """
    if not clock:
        return []
    now_u = _utc(now)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for mark in clock.get("marks") or []:
        if not isinstance(mark, dict):
            continue
        name = str(mark.get("name") or "").strip()
        if not name:
            continue
        when = _arrival(clock, mark)
        if when is None:
            continue
        start = when - timedelta(days=before_days)
        end = when + timedelta(days=after_days)
        if now_u < start or now_u > end:
            continue
        key = slug(name)
        if key in seen:
            continue
        seen.add(key)
        item = {
            "name": name,
            "slug": key,
            "arrival": when,
            "lat": mark.get("lat"),
            "lon": mark.get("lon"),
            "url": mark.get("url"),
        }
        out.append(item)
    return out


def official_stop_in_window(
    name: str,
    now: datetime | None = None,
    *,
    lat: float | None = None,
    lon: float | None = None,
) -> dict[str, Any] | None:
    """Escale du voyage officiel dans la fenêtre J-10 → J+2, sinon None."""
    from voyage_clock import OFFICIAL_VOYAGE_ID  # noqa: PLC0415
    from voyage_store import load_voyage  # noqa: PLC0415

    label = str(name or "").strip()
    if not label:
        return None
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    clock = (voy or {}).get("clock") if isinstance(voy, dict) else None
    key = slug(label)
    for stop in stops_in_window(clock, _utc(now)):
        if stop.get("slug") != key:
            continue
        out = dict(stop)
        if out.get("lat") is None and isinstance(lat, (int, float)):
            out["lat"] = lat
        if out.get("lon") is None and isinstance(lon, (int, float)):
            out["lon"] = lon
        return out
    return None


def _cache_get(ns: str, key: str, max_age_s: float | None = None) -> dict[str, Any] | None:
    import pearl_store  # noqa: PLC0415

    hit = pearl_store.kv_get(ns, key, max_age_s)
    val = (hit or {}).get("value")
    return val if isinstance(val, dict) else None


def _cache_put(ns: str, key: str, value: Any) -> None:
    import pearl_store  # noqa: PLC0415

    pearl_store.kv_put(ns, key, value)


def _index_key(day: str) -> str:
    return f"index:{day}"


def _index_get(day: str) -> list[dict[str, Any]]:
    import pearl_store  # noqa: PLC0415

    hit = pearl_store.kv_get(WATCH_NS, _index_key(day))
    val = (hit or {}).get("value")
    if isinstance(val, list):
        return [e for e in val if isinstance(e, dict)]
    return []


def _index_put(day: str, entry: dict[str, Any]) -> None:
    rows = [e for e in _index_get(day) if e.get("id") != entry.get("id")]
    rows.append(entry)
    _cache_put(WATCH_NS, _index_key(day), rows)
    # Index « toutes escales » : une veille faite à J-10 doit rester rattachée au sac
    # jusqu'à l'arrivée, pas seulement trois jours (index par jour, hérité).
    rows_all = [e for e in _index_get("all") if e.get("id") != entry.get("id")]
    rows_all.append(entry)
    _cache_put(WATCH_NS, _index_key("all"), rows_all)


def watch_cache_key(name: str, qid: str = "avis", now: datetime | None = None) -> str:
    """Une clé par escale et par question de la liste — pas une moisson."""
    q = str(qid or "avis").strip() or "avis"
    return f"{slug(name)}:{q}"


def _done_key(name: str) -> str:
    return f"done:{slug(name)}"


def watch_done(name: str) -> bool:
    """L'escale a déjà eu sa veille (entrée écrite, ou recherche sans résultat)."""
    return _cache_get(WATCH_NS, _done_key(name)) is not None


def _first_url(results: list[Any]) -> str | None:
    for item in results:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if isinstance(url, str) and url.startswith("http"):
            return url
    return None


def _fallback_sentence(results: list[Any], facts: Any) -> str:
    for item in results:
        if not isinstance(item, dict):
            continue
        raw = item.get("content") or item.get("title") or ""
        if not isinstance(raw, str) or not raw.strip():
            continue
        first = raw.strip().split("\n")[0].strip()
        cleaned, _ = filter_numbers(first, facts)
        if cleaned:
            return cleaned.split(".")[0].strip()
    return ""


async def _summarize(
    system: str,
    user: str,
    facts: Any,
    fallback: str,
    *,
    client: httpx.AsyncClient | None,
) -> tuple[str, str]:
    if not llm_budget.allow("fast"):
        text, _ = filter_numbers(fallback, facts)
        return (text or "").strip(), "budget"
    try:
        text, source = await cascade_text(
            system, user, client, tier="fast", fallback=fallback or "",
            facts=facts, max_tokens=80,
        )
    except Exception as exc:
        log.debug("résumé veille/enrich : %s", exc)
        text, _ = filter_numbers(fallback, facts)
        return (text or "").strip(), "rules"
    cleaned, _ = filter_numbers(text or "", facts)
    out = (cleaned or "").strip()
    if not out:
        out, _ = filter_numbers(fallback, facts)
        out = (out or "").strip()
        if source not in {"budget", "rules"}:
            source = "rules"
    # Une phrase : on coupe au premier point final.
    if "." in out:
        out = out.split(".")[0].strip()
    return out, source


async def search_watch(
    port: str,
    *,
    qid: str = "avis",
    include_domains: Iterable[str] | None = None,
    now: datetime | None = None,
    query_date: datetime | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Un search Tavily pour une question de la liste. Cache ns `watch`."""
    when = _utc(now)
    qdate = _utc(query_date) if query_date is not None else when
    query = format_watch_question(qid, port, qdate)
    empty = {"results": [], "credits": 0, "cached": False, "query": query or "", "qid": qid}
    if not query:
        return {**empty, "reason": "bad-question"}
    if not watch_enabled():
        return {**empty, "reason": "off"}
    key = watch_cache_key(port, qid, when)
    hit = _cache_get(WATCH_NS, key)
    if hit and "results" in hit:
        return {**hit, "cached": True, "qid": qid}
    if not tavily_client.api_key():
        return {**empty, "reason": "no-key"}
    if not llm_budget.allow_tavily():
        return {**empty, "reason": "budget"}
    if _watch_search_count(_day(when)) >= watch_daily_search_cap():
        return {**empty, "reason": "cap"}
    # Compté avant l'appel : une recherche qui lève (timeout Tavily) reste dans
    # le plafond du jour, sinon chaque GET relance une tentative sans fin.
    _watch_search_inc(_day(when))
    data = await tavily_client.search(
        query,
        topic="news",
        days=SEARCH_DAYS,
        max_results=SEARCH_MAX,
        include_domains=include_domains,
        client=client,
    )
    if data.get("credits"):
        llm_budget.remember_tavily_port(port)
    stored = {
        "results": data.get("results") or [],
        "credits": data.get("credits") or 0,
        "query": query,
        "qid": qid,
        "day": _day(when),
    }
    status = data.get("status") if isinstance(data, dict) else None
    if isinstance(status, int) and status >= 400:
        stored["reason"] = "http-error"
        stored["status"] = status
        # Une panne temporaire ne doit pas empêcher une nouvelle tentative
        # pour cette question pendant le reste de la journée.
        return {**stored, "cached": False}
    _cache_put(WATCH_NS, key, stored)
    return {**stored, "cached": False}


def news_entry(
    stop: dict[str, Any],
    text: str,
    url: str | None,
    now: datetime,
    *,
    source: str | None = None,
    question: str | None = None,
    rounds: int | None = None,
) -> dict[str, Any]:
    when = _utc(now)
    day = _day(when)
    name = str(stop.get("name") or "").strip()
    arrival = stop.get("arrival")
    exp = expires_at(arrival if isinstance(arrival, datetime) and _utc(arrival) > when else when)
    host = _host_of(url)
    qid = str(question or "").strip() or None
    if qid and qid not in WATCH_QUESTION_IDS:
        qid = None
    entry: dict[str, Any] = {
        "id": f"news:{slug(name)}",
        "kind": "news",
        "t": to_iso(when.replace(hour=12, minute=0, second=0, microsecond=0)),
        "event": "watch",
        "name": name,
        "text": text,
        "url": url,
        "source": source or host,
        "expires": to_iso(exp),
        "title": {"fr": "Veille", "en": "Watch"},
        "facts": {"name": name, "day": day},
        "basis": "tavily",
        "question": qid,
        "rounds": rounds,
    }
    lat, lon = stop.get("lat"), stop.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        entry["lat"] = round(float(lat), 4)
        entry["lon"] = round(float(lon), 4)
        entry["entity"] = {
            "kind": "escale",
            "name": name,
            "lat": round(float(lat), 4),
            "lon": round(float(lon), 4),
            "url": url,
        }
    return {k: v for k, v in entry.items() if v is not None}


async def decide_second_question(
    results: list[Any],
    remaining: Iterable[str],
    *,
    client: httpx.AsyncClient | None = None,
    cascade: Any = None,
) -> str | None:
    """Nano choisit un id de remaining, ou None. Hors liste → refusée."""
    left = [q for q in WATCH_QUESTION_IDS if q in {str(x) for x in remaining}]
    if not left:
        return None
    if not llm_budget.allow("nano"):
        return None if _has_answer(results) else left[0]
    fn = cascade or cascade_text
    user = json.dumps(
        {"remaining": left, "results": results[:5]},
        ensure_ascii=False, default=str,
    )
    try:
        text, _src = await fn(
            ROUND2_SYSTEM, user, client, tier="nano", fallback="", facts=user, max_tokens=40,
        )
    except Exception as exc:
        log.debug("tour 2 veille : %s", exc)
        text = ""
    picked = parse_second_question(text or "", left)
    if picked:
        return picked
    return None if _has_answer(results) else left[0]


# Un seul watch_stop à la fois (GET /escale et boucle du jour) : les plafonds
# sont lus avant l'appel Tavily et comptés après, deux veilles en parallèle
# passaient donc toutes les deux le contrôle. Un verrou par boucle asyncio.
_WATCH_LOCK: tuple[Any, asyncio.Lock] | None = None


def _watch_lock() -> asyncio.Lock:
    global _WATCH_LOCK
    loop = asyncio.get_running_loop()
    if _WATCH_LOCK is None or _WATCH_LOCK[0] is not loop:
        _WATCH_LOCK = (loop, asyncio.Lock())
    return _WATCH_LOCK[1]


async def watch_stop(
    stop: dict[str, Any],
    now: datetime,
    *,
    include_domains: Iterable[str] | None = None,
    client: httpx.AsyncClient | None = None,
    cascade: Any = None,
) -> dict[str, Any] | None:
    """Veille d'une escale : deux tours max, questions de la liste, phrase + URL.

    Drapeau fermé → rien. Déjà faite (`done:<slug>`) → rien. Une veille à la
    fois : `done` et les plafonds sont relus une fois le verrou pris."""
    name = str(stop.get("name") or "").strip()
    if not name or watch_done(name):
        return None
    if not watch_enabled():
        return None
    async with _watch_lock():
        if watch_done(name) or not watch_enabled():
            return None
        return await _watch_stop_locked(
            stop, now, include_domains=include_domains, client=client, cascade=cascade,
        )


async def _watch_stop_locked(
    stop: dict[str, Any],
    now: datetime,
    *,
    include_domains: Iterable[str] | None,
    client: httpx.AsyncClient | None,
    cascade: Any,
) -> dict[str, Any] | None:
    name = str(stop.get("name") or "").strip()
    when = _utc(now)
    arrival = stop.get("arrival")
    qdate = _utc(arrival) if isinstance(arrival, datetime) else when
    domains = list(include_domains) if include_domains is not None else official_domains(
        name, [stop.get("url")] if stop.get("url") else None,
    )
    used: list[str] = []
    all_results: list[Any] = []
    last_qid = WATCH_QUESTION_IDS[0]
    qid: str | None = WATCH_QUESTION_IDS[0]
    completed_round = False
    while (
        qid
        and qid not in used
        and len(used) < MAX_WATCH_ROUNDS
        and len(used) < MAX_WATCH_SEARCHES_PER_STOP
    ):
        found = await search_watch(
            name, qid=qid, include_domains=domains or None,
            now=when, query_date=qdate, client=client,
        )
        used.append(qid)
        last_qid = qid
        if found.get("reason") in {"off", "no-key", "budget", "cap", "bad-question", "http-error"}:
            break
        completed_round = True
        all_results.extend(found.get("results") or [])
        remaining = [q for q in WATCH_QUESTION_IDS if q not in used]
        if len(used) >= MAX_WATCH_ROUNDS or not remaining:
            break
        nxt = await decide_second_question(
            all_results, remaining, client=client, cascade=cascade,
        )
        qid = nxt
    results = all_results
    if not completed_round:
        return None
    facts = {"port": name, "results": results}
    fallback = _fallback_sentence(results, facts)
    url = _first_url(results)
    if not results and not fallback:
        _cache_put(WATCH_NS, _done_key(name), {
            "day": _day(when), "results": 0, "rounds": len(used), "questions": used,
        })
        return None
    user = (
        f"Escale : {name}\n"
        f"Résultats Tavily (faits, ne pas inventer de chiffre) :\n"
        f"{results!r}\n\n"
        "Une phrase, sans chiffre nouveau."
    )
    sentence, source = await _summarize(
        WATCH_SYSTEM, user, facts, fallback, client=client,
    )
    if not sentence:
        return None
    entry = news_entry(
        stop, sentence, url, now, source=source,
        question=last_qid, rounds=len(used),
    )
    try:
        import voyage_journal  # noqa: PLC0415

        voyage_journal.record_news(entry)
    except Exception as exc:
        log.debug("journal news : %s", exc)
    _index_put(_day(now), entry)
    _cache_put(WATCH_NS, _done_key(name), {
        "day": _day(when), "results": len(results), "id": entry["id"],
        "rounds": len(used), "questions": used,
    })
    return entry


async def run_daily_watch(
    voy: dict[str, Any] | None,
    now: datetime | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Passe : prochaines escales (J-10 → J+2), deux tours max, drapeau obligatoire."""
    when = _utc(now)
    if not watch_enabled():
        return {"watched": 0, "wrote": 0, "skipped": True, "reason": "off"}
    clock = (voy or {}).get("clock") if isinstance(voy, dict) else None
    stops = stops_in_window(clock, when)
    if not stops:
        return {"watched": 0, "wrote": 0, "skipped": True, "reason": "no-stop"}
    if not tavily_client.api_key():
        return {"watched": 0, "wrote": 0, "skipped": True, "reason": "no-key"}
    wrote = 0
    for stop in stops:
        try:
            entry = await watch_stop(stop, when, client=client)
        except Exception as exc:
            log.debug("veille %s : %s", stop.get("name"), exc)
            continue
        if entry:
            wrote += 1
    return {"watched": len(stops), "wrote": wrote, "skipped": False}


def enrich_key(item: dict[str, Any] | None) -> str | None:
    if not isinstance(item, dict):
        return None
    for raw in (item.get("url"), item.get("visit_url"), item.get("manager_url")):
        if isinstance(raw, str) and raw.startswith("http"):
            return raw.strip()
    return None


def _enrich_day_count(day: str | None = None) -> int:
    hit = _cache_get(ENRICH_NS, f"day-count:{day or _day(_utc())}")
    try:
        return int((hit or {}).get("n") or 0)
    except (TypeError, ValueError):
        return 0


def _enrich_day_inc(day: str | None = None) -> None:
    d = day or _day(_utc())
    _cache_put(ENRICH_NS, f"day-count:{d}", {"n": _enrich_day_count(d) + 1})


def enrich_daily_cap() -> int:
    import os  # noqa: PLC0415

    raw = (os.environ.get("NAVIGUIDE_ENRICH_DAILY") or "").strip()
    if not raw:
        return ENRICH_DAILY_CAP
    try:
        return max(0, int(raw))
    except ValueError:
        return ENRICH_DAILY_CAP


async def enrich_entity(
    item: dict[str, Any],
    *,
    client: httpx.AsyncClient | None = None,
    extract: bool = True,
) -> dict[str, Any] | None:
    """Phrase sourcée, une fois, cache définitif. Sans URL : rien."""
    url = enrich_key(item)
    if not url:
        return item.get("enrich") if isinstance(item.get("enrich"), dict) else None
    hit = _cache_get(ENRICH_NS, url)
    if hit and hit.get("text"):
        item["enrich"] = hit
        return hit
    if not extract:
        return None
    if not tavily_client.api_key() or not llm_budget.allow_tavily():
        return None
    if _enrich_day_count() >= enrich_daily_cap():
        return None
    data = await tavily_client.extract([url], depth="basic", client=client)
    _enrich_day_inc()
    raw = (data.get("text") or "")[:MAX_EXTRACT_CHARS]
    facts = {"name": item.get("name"), "url": url, "extract": raw}
    fallback = ""
    if raw:
        fallback, _ = filter_numbers(raw.split("\n")[0].strip(), facts)
    user = (
        f"Entité : {item.get('name') or ''}\n"
        f"URL : {url}\n"
        f"Extrait officiel :\n{raw}\n\n"
        "Une phrase sourcée, sans chiffre nouveau."
    )
    sentence, source = await _summarize(
        ENRICH_SYSTEM, user, facts, fallback or "", client=client,
    )
    if not sentence:
        return None
    stored = {"text": sentence, "url": url, "source": source}
    _cache_put(ENRICH_NS, url, stored)
    item["enrich"] = stored
    return stored


def _science_items(bag: dict[str, Any]) -> list[dict[str, Any]]:
    sci = bag.get("science")
    if isinstance(sci, dict):
        items = sci.get("nearby") or []
    elif isinstance(sci, list):
        items = sci
    else:
        items = []
    return [it for it in items if isinstance(it, dict)]


async def enrich_bag(
    bag: dict[str, Any],
    *,
    client: httpx.AsyncClient | None = None,
    extract: bool = True,
) -> dict[str, Any]:
    for item in _science_items(bag):
        try:
            await enrich_entity(item, client=client, extract=extract)
        except Exception as exc:
            log.debug("enrich science : %s", exc)
    for item in bag.get("projects") or []:
        if not isinstance(item, dict):
            continue
        try:
            await enrich_entity(item, client=client, extract=extract)
        except Exception as exc:
            log.debug("enrich projet : %s", exc)
    return bag


def attach_cached_news(bag: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    when = _utc(now)
    seen = {n.get("id") for n in (bag.get("news") or []) if isinstance(n, dict)}
    extra: list[dict[str, Any]] = []
    days = ["all"] + [(when - timedelta(days=delta)).strftime("%Y-%m-%d") for delta in (0, 1, 2)]
    for day in days:
        for entry in _index_get(day):
            if expired(entry, when) or entry.get("id") in seen:
                continue
            seen.add(entry.get("id"))
            extra.append(entry)
    if extra:
        bag["news"] = list(bag.get("news") or []) + extra
    return bag


def attach_cached(bag: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Lecture seule du cache (pas de réseau) : news du jour + phrases enrich."""
    attach_cached_news(bag, now)
    for item in _science_items(bag) + [p for p in (bag.get("projects") or []) if isinstance(p, dict)]:
        url = enrich_key(item)
        if not url:
            continue
        hit = _cache_get(ENRICH_NS, url)
        if hit and hit.get("text"):
            item["enrich"] = hit
    return bag


async def run_daily_enrich(
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Parcourt les perles riches : extract une fois par URL officielle."""
    import pearl_store  # noqa: PLC0415
    from ici_engine import thin_cache_put  # noqa: PLC0415

    if not tavily_client.api_key():
        return {"entities": 0, "wrote": 0, "skipped": True, "reason": "no-key"}
    wrote = 0
    seen = 0
    for key, row in pearl_store.iter_pearls("rich"):
        bag = row.get("bag")
        if not isinstance(bag, dict):
            continue
        before = {
            enrich_key(it)
            for it in _science_items(bag) + list(bag.get("projects") or [])
            if isinstance(it, dict) and isinstance((it.get("enrich") or {}).get("text"), str)
        }
        await enrich_bag(bag, client=client, extract=True)
        after = {
            enrich_key(it)
            for it in _science_items(bag) + list(bag.get("projects") or [])
            if isinstance(it, dict) and isinstance((it.get("enrich") or {}).get("text"), str)
        }
        seen += len(_science_items(bag)) + len(bag.get("projects") or [])
        if after - before:
            wrote += len(after - before)
            try:
                lat, lon = float(key.split(":")[0]), float(key.split(":")[1])
            except Exception:
                lat = lon = None
            thin_cache_put(key, bag, "rich", lat, lon)
    return {"entities": seen, "wrote": wrote, "skipped": False}


async def run_daily(
    voy: dict[str, Any] | None = None,
    now: datetime | None = None,
    *,
    client: httpx.AsyncClient | None = None,
    enrich: bool = True,
) -> dict[str, Any]:
    """Veille des escales. L'enrichissement des perles est optionnel (mémoire)."""
    from voyage_clock import OFFICIAL_VOYAGE_ID  # noqa: PLC0415
    from voyage_store import load_voyage  # noqa: PLC0415

    trip = voy if voy is not None else load_voyage(OFFICIAL_VOYAGE_ID)
    watch = await run_daily_watch(trip, now, client=client)
    if not enrich:
        return {
            "watch": watch,
            "enrich": {"entities": 0, "wrote": 0, "skipped": True, "reason": "watch-only"},
        }
    enrich_out = await run_daily_enrich(client=client)
    return {"watch": watch, "enrich": enrich_out}
