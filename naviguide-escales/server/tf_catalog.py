"""Garde de disponibilité des modèles Token Factory (C1-b).

Avant un appel Nemotron, on vérifie que l'id configuré pour le palier figure
dans le catalogue de l'hôte qui va le servir : `GET {base}/models`. Cette
lecture est gratuite (aucune inférence, aucun jeton), mise en cache dans
`pearl_store` (6 h par défaut) et jamais refaite plus d'une fois par
intervalle de repli après un échec. Elle ne part que là où un appel payant
partirait de toute façon (la cascade l'appelle après `llm_budget.allow`).

Le catalogue a déjà bougé : Nano 30B et Super 120B retirés le 9 nov. 2026,
Super VL servi seulement par l'hôte UE (api.tokenfactory.nebius.com). Si un
id manque, la cascade prend un autre Nemotron Token Factory présent, avec son
propre libellé (source et modèle réels) et un compteur `modelGuard` dans
`/ici/warm/status` — jamais un repli silencieux.

Désactivable : NAVIGUIDE_TF_MODEL_GUARD=0 (les tests le posent par défaut).
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger("naviguide-simulator.tf-catalog")

NS = "tf-catalog"
DEFAULT_TTL_S = 6 * 3600.0
# Après un échec de lecture (réseau, 401, réponse illisible) : pas de nouvel
# essai avant ce délai. Le garde reste « inconnu » et ne remplace rien.
RETRY_AFTER_FAIL_S = 600.0
TIMEOUT = httpx.Timeout(5.0, connect=3.0)
_DEADLINE: ContextVar[float | None] = ContextVar("tf_catalog_deadline", default=None)


def set_deadline(deadline: float) -> Token:
    return _DEADLINE.set(deadline)


def reset_deadline(token: Token) -> None:
    _DEADLINE.reset(token)

_LOCKS: dict[str, asyncio.Lock] = {}


def enabled() -> bool:
    raw = (os.environ.get("NAVIGUIDE_TF_MODEL_GUARD") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def ttl_s() -> float:
    raw = (os.environ.get("NAVIGUIDE_TF_CATALOG_TTL_S") or "").strip()
    try:
        val = float(raw)
    except ValueError:
        return DEFAULT_TTL_S
    return val if math.isfinite(val) and val > 0 else DEFAULT_TTL_S


def _norm_base(base: str) -> str:
    return (base or "").strip().rstrip("/")


def _get(base: str) -> dict[str, Any] | None:
    import pearl_store  # noqa: PLC0415

    hit = pearl_store.kv_get(NS, _norm_base(base))
    val = (hit or {}).get("value")
    return val if isinstance(val, dict) else None


def _put(base: str, value: dict[str, Any]) -> None:
    import pearl_store  # noqa: PLC0415

    pearl_store.kv_put(NS, _norm_base(base), value)


def invalidate(base: str) -> None:
    """Expire a cached catalog after the API rejects a model id."""
    import pearl_store  # noqa: PLC0415

    pearl_store.kv_delete(NS, _norm_base(base))


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fresh(entry: dict[str, Any] | None, now: float) -> bool:
    if not entry:
        return False
    try:
        ts = float(entry.get("ts") or 0)
    except (TypeError, ValueError):
        return False
    if entry.get("ok"):
        return now - ts < ttl_s()
    return now - ts < RETRY_AFTER_FAIL_S


def parse_catalog(data: Any) -> list[str] | None:
    """Ids d'une réponse OpenAI `/models`. None si la forme est inattendue."""
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        return None
    source = data["data"]
    if not source:
        return []
    ids = [str(m.get("id")).strip() for m in source if isinstance(m, dict) and m.get("id") and str(m.get("id")).strip()]
    return ids or None


async def refresh(base: str, key: str, client: httpx.AsyncClient, remaining: float | None = None) -> dict[str, Any]:
    """Lit le catalogue de l'hôte (un GET, sans jeton facturé) et le met en cache."""
    b = _norm_base(base)
    started = time.monotonic()
    entry: dict[str, Any]
    try:
        request_timeout = TIMEOUT if remaining is None else httpx.Timeout(
            min(TIMEOUT.read, max(0.001, remaining)),
            connect=min(TIMEOUT.connect, max(0.001, remaining)),
        )
        r = await client.get(
            f"{b}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=request_timeout,
        )
        ms = int(round((time.monotonic() - started) * 1000))
        if r.status_code >= 400:
            entry = {"ok": False, "reason": f"HTTP {r.status_code}", "ms": ms}
        else:
            ids = parse_catalog(r.json())
            entry = {"ok": True, "ids": ids, "ms": ms} if ids is not None else {"ok": False, "reason": "catalogue illisible", "ms": ms}
    except Exception as exc:  # réseau, JSON : le garde reste « inconnu »
        entry = {"ok": False, "reason": type(exc).__name__}
    entry["ts"] = time.time()
    entry["at"] = _now_iso()
    _put(b, entry)
    if not entry["ok"]:
        log.warning("catalogue Token Factory %s : %s", b, entry.get("reason"))
    return entry


async def ensure_fresh(base: str, key: str, client: httpx.AsyncClient) -> dict[str, Any] | None:
    """Catalogue en cache, relu seulement s'il a expiré. Jamais d'exception."""
    if not enabled() or not key:
        return None
    b = _norm_base(base)
    try:
        entry = _get(b)
        if _fresh(entry, time.time()):
            return entry
        lock = _LOCKS.setdefault(b, asyncio.Lock())
        deadline = _DEADLINE.get()
        remaining = max(0.0, deadline - time.monotonic()) if deadline is not None else None
        if remaining is not None and remaining <= 0:
            return None

        async def read():
            async with lock:
                entry = _get(b)
                if _fresh(entry, time.time()):
                    return entry
                left = max(0.0, deadline - time.monotonic()) if deadline is not None else None
                if left is not None and left <= 0:
                    return None
                return await refresh(b, key, client, left)

        if remaining is None:
            return await read()
        async with asyncio.timeout(remaining):
            return await read()
    except Exception as exc:
        log.warning("catalogue Token Factory %s : %r", b, exc)
        return None


def has_model(base: str, model: str) -> bool | None:
    """True / False d'après le dernier catalogue lu ; None si inconnu (fail-open)."""
    entry = _get(base)
    if not entry or not entry.get("ok"):
        return None
    ids = entry.get("ids")
    if not isinstance(ids, list):
        return None
    want = (model or "").strip().lower()
    return any(str(i).strip().lower() == want for i in ids)


def status() -> dict[str, Any]:
    """État des catalogues déjà lus (cache seulement, aucun appel réseau)."""
    import pearl_store  # noqa: PLC0415

    out: dict[str, Any] = {}
    for base in sorted(pearl_store.kv_keys(NS)):
        entry = _get(base)
        if not entry:
            continue
        row: dict[str, Any] = {"ok": bool(entry.get("ok")), "at": entry.get("at")}
        if entry.get("ok"):
            row["models"] = len(entry.get("ids") or [])
        else:
            row["reason"] = entry.get("reason")
        if isinstance(entry.get("ms"), int):
            row["ms"] = entry["ms"]
        out[base] = row
    return out


async def prefetch(bases: list[str], key: str) -> dict[str, Any]:
    """Au démarrage du serveur : lit une fois chaque hôte configuré (gratuit)."""
    if not enabled() or not key:
        return {}
    out: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for base in dict.fromkeys(_norm_base(b) for b in bases if b):
            out[base] = await ensure_fresh(base, key, client)
    return out


def reset() -> None:
    """Tests : oublie les verrous (le cache vit dans pearl_store, isolé par test)."""
    _LOCKS.clear()
