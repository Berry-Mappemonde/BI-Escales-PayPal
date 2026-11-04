"""Cache de lecture des récits d'événements.

`POST /ici/story` (geste « Rédigé » seulement) lit le cache SQLite
(`pearl_store.kv`, ns « story », 7 jours) indexé par `(type, stableKey, lang)`,
puis `write_story` → `cascade_text(tier="write")` (Token Factory Super →
OpenRouter → Claude → règles) et garde le résultat, **avec `source`**.

Plus de pré-génération en fond : un récit ne s'écrit que sur la
pilule Rédigé.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any, Optional

STORY_TTL_S = 7 * 86400.0
CACHEABLE_TYPES = frozenset({"zee-enter", "zee-exit", "amp-enter", "amp-ahead", "poe-ahead"})


def budget_per_day() -> int:
    try:
        return max(0, int(os.environ.get("NAVIGUIDE_STORY_BUDGET_PER_DAY") or 300))
    except ValueError:
        return 300


# ── key / lookup ────────────────────────────────────────────────────────────

def body_lang(body: dict | None) -> str:
    return str((body or {}).get("lang") or "fr")[:2].lower()


def story_key(body: dict | None) -> Optional[str]:
    """(type, stableKey, lang) → key, or None when this event is not cacheable."""
    if not isinstance(body, dict):
        return None
    typ = str(body.get("type") or body.get("event") or "")
    stable = body.get("stableKey")
    if typ not in CACHEABLE_TYPES or not stable:
        return None
    return f"{typ}|{stable}|{body_lang(body)}"


# ── traduction FR → EN, cache par (hash, lang) ────────────────

TRANSLATE_NS = "story-tr"
TRANSLATE_TTL_S = STORY_TTL_S


def translate_key(text: str, lang: str) -> str:
    h = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
    return f"{(lang or 'en')[:2].lower()}|{h}"


def get_translated(text: str, lang: str) -> Optional[dict]:
    if not text or not (lang or "").lower().startswith("en"):
        return None
    import pearl_store  # noqa: PLC0415
    hit = pearl_store.kv_get(TRANSLATE_NS, translate_key(text, lang), TRANSLATE_TTL_S)
    val = (hit or {}).get("value")
    if not isinstance(val, dict) or not val.get("text"):
        return None
    return {"text": val["text"], "source": val.get("source") or "cache"}


def put_translated(text: str, lang: str, result: dict | None) -> bool:
    if not text or not (lang or "").lower().startswith("en") or not isinstance(result, dict) or not result.get("text"):
        return False
    import pearl_store  # noqa: PLC0415
    return pearl_store.kv_put(TRANSLATE_NS, translate_key(text, lang), {
        "text": result["text"],
        "source": result.get("source"),
    })


async def translate_through_cache(text: str, lang: str, client=None) -> tuple[str, str]:
    """Lightning translation, keyed by (hash(text), lang). FR is a no-op."""
    src = (text or "").strip()
    lg = (lang or "fr")[:2].lower()
    if not src or lg != "en":
        return src, "rules"
    hit = get_translated(src, lg)
    if hit:
        return hit["text"], hit.get("source") or "cache"
    from story_cascade import translate  # noqa: PLC0415
    out, source = await translate(src, "en", client, facts=src)
    put_translated(src, "en", {"text": out, "source": source})
    return out, source


def get_cached(body: dict | None) -> Optional[dict]:
    key = story_key(body)
    if not key:
        return None
    import pearl_store  # noqa: PLC0415
    hit = pearl_store.kv_get("story", key, STORY_TTL_S)
    if not hit or not isinstance(hit.get("value"), dict) or not hit["value"].get("text"):
        return None
    v = hit["value"]
    src = v.get("source") or "cache"
    return {
        "status": "ready",
        "text": v["text"],
        "engine": f"cache:{v.get('engine') or src or 'llm'}",
        "source": "cache",
        "cascade": "tokenfactory-openrouter-claude",
        "tavily": None,
        "nvidia": v.get("engine") or src,
        "cached": True,
        "cachedAt": hit["ts"],
    }


def put_cached(body: dict | None, result: dict | None) -> bool:
    key = story_key(body)
    if not key or not isinstance(result, dict) or result.get("status") != "ready" or not result.get("text"):
        return False
    import pearl_store  # noqa: PLC0415
    return pearl_store.kv_put("story", key, {
        "text": result["text"],
        "engine": result.get("engine"),
        "source": result.get("source"),
        "type": body.get("type"),
    })


# ── budget ──────────────────────────────────────────────────────────────────

def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def budget_used_today() -> int:
    import pearl_store  # noqa: PLC0415
    hit = pearl_store.kv_get("story-budget", _today())
    try:
        return int((hit or {}).get("value") or 0)
    except (TypeError, ValueError):
        return 0


def budget_left() -> int:
    return max(0, budget_per_day() - budget_used_today())


def _spend(n: int = 1) -> None:
    import pearl_store  # noqa: PLC0415
    pearl_store.kv_put("story-budget", _today(), budget_used_today() + n)


# ── the cascade, through the cache ──────────────────────────────────────────

async def _store_en_from_fr(body: dict, fr_text: str, client=None) -> dict[str, Any]:
    text, source = await translate_through_cache(fr_text, "en", client)
    result = {
        "status": "ready",
        "text": text,
        "engine": source,
        "source": source,
        "cascade": "tokenfactory-openrouter-claude",
        "tavily": None,
        "nvidia": source,
        "cached": False,
        "translatedFrom": "fr",
    }
    if put_cached(body, result):
        _spend(1)
    return result


def _prepared_official(body: dict | None) -> dict | None:
    """Récit préparé une fois, s'il est dans le stock. Sinon le chemin à la demande."""
    try:
        import stories_once  # noqa: PLC0415
    except Exception:
        return None
    return stories_once.prepared(body)


async def story_through_cache(body: dict, client=None, writer=None) -> dict[str, Any]:
    """What POST /ici/story returns: the cache when it knows, else the cascade
    (`writer`, default story_cascade.write_story → cascade_text tier=write)
    — and remember, with `source` kept on the payload.

    Langue EN : on réutilise le récit FR en cache, puis Lightning
    traduit (clé `story` et `story-tr` portent `lang`).
    """
    if writer is None:
        from story_cascade import write_story  # noqa: PLC0415
        writer = write_story
    prepared_hit = _prepared_official(body)
    if prepared_hit is not None:
        return prepared_hit
    hit = get_cached(body)
    if hit:
        return hit
    if body_lang(body) == "en":
        fr_body = {**body, "lang": "fr"}
        fr_hit = get_cached(fr_body)
        if fr_hit and fr_hit.get("text"):
            return await _store_en_from_fr(body, fr_hit["text"], client)
        if story_key(body):
            fr_out = await writer(fr_body, client) if client is not None else await writer(fr_body)
            fr_result = {**(fr_out or {}), "cached": False}
            if fr_result.get("status") == "ready" and not fr_result.get("source"):
                fr_result["source"] = fr_result.get("engine") or "rules"
            if put_cached(fr_body, fr_result):
                _spend(1)
            if fr_result.get("status") == "ready" and fr_result.get("text"):
                return await _store_en_from_fr(body, fr_result["text"], client)
            return fr_result
    out = await writer(body, client) if client is not None else await writer(body)
    result = {**(out or {}), "cached": False}
    if result.get("status") == "ready" and not result.get("source"):
        result["source"] = result.get("engine") or "rules"
    if put_cached(body, result):
        _spend(1)
    return result


def status() -> dict[str, Any]:
    """Lecture du cache seulement — plus d'étape de pré-génération."""
    import pearl_store  # noqa: PLC0415
    return {
        "skipped": "on-demand",
        "stored": pearl_store.kv_count("story"),
        "budgetLeftToday": budget_left(),
    }


# ── film script (ns « film-story ») ───────────────────────────

FILM_NS = "film-story"
FILM_TTL_S = 86400.0  # 1×/jour ; une nouvelle escale change la clé (hash journal)


def film_cache_key(journal_hash: str, lang: str, seconds: int) -> str:
    try:
        n = int(seconds)
    except (TypeError, ValueError):
        n = 150
    if n < 0:
        n = 0
    return f"{journal_hash}|{(lang or 'fr')[:2].lower()}|{n}"


def get_film_cached(key: str) -> Optional[dict]:
    if not key:
        return None
    import pearl_store  # noqa: PLC0415
    hit = pearl_store.kv_get(FILM_NS, key, FILM_TTL_S)
    val = (hit or {}).get("value")
    return val if isinstance(val, dict) else None


def put_film_cached(key: str, value: dict | None) -> bool:
    if not key or not isinstance(value, dict):
        return False
    import pearl_store  # noqa: PLC0415
    return pearl_store.kv_put(FILM_NS, key, value)
