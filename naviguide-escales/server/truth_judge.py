"""Juge de vérité.

Tavily relit la page officielle d'une fiche PoE Gold ; Nemotron 3 Ultra
(tier `judge`) dit ce qui n'est plus soutenu. Aucun chiffre nouveau :
`filter_numbers` sur `stale_hint`. Cache 7 jours, ns `truth`, clé (ZEE, URL).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

import llm_budget
import tavily_client
from story_cascade import cascade_text, filter_numbers

log = logging.getLogger("naviguide-simulator.truth")

NS = "truth"
TTL_S = 7 * 86400.0
MAX_EXTRACT_CHARS = 6_000 * 4  # ≤ 6 k tokens, ~4 car. / token
_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_INFLIGHT: dict[str, asyncio.Future] = {}

SYSTEM = (
    "Tu es un juge de vérité. Tu compares les faits d'une fiche officielle "
    "à l'extrait de sa page source. Tu ne produis aucun chiffre qui n'est pas "
    "déjà dans les faits ou l'extrait. Réponds uniquement par un JSON : "
    '{"supported": ["..."], "unsupported": ["..."], "stale_hint": null}. '
    "supported et unsupported : phrases de la fiche, mot pour mot. "
    "stale_hint : une phrase courte ou null, sans chiffre nouveau. "
    "Thinking OFF."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def cache_key(zee: Any, url: str) -> str:
    mrgid = None
    if isinstance(zee, dict):
        mrgid = zee.get("mrgid")
    elif zee is not None:
        mrgid = zee
    return f"{mrgid or 'x'}:{url.strip()}"


def unverifiable(*, reason: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "status": "unverifiable",
        "checkedAt": _now_iso(),
        "supported": [],
        "unsupported": [],
        "stale_hint": None,
    }
    if reason:
        out["reason"] = reason
    return out


def _clip_extract(text: str) -> str:
    raw = (text or "").strip()
    if len(raw) <= MAX_EXTRACT_CHARS:
        return raw
    return raw[:MAX_EXTRACT_CHARS]


def _parse_verdict(text: str) -> dict[str, Any] | None:
    raw = _JSON_FENCE.sub("", (text or "").strip()).strip()
    if not raw:
        return None
    try:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None
        data = json.loads(raw[start:end + 1])
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    supported = [s.strip() for s in (data.get("supported") or []) if isinstance(s, str) and s.strip()]
    unsupported = [s.strip() for s in (data.get("unsupported") or []) if isinstance(s, str) and s.strip()]
    hint = data.get("stale_hint")
    if hint is not None and not isinstance(hint, str):
        hint = None
    if isinstance(hint, str) and not hint.strip():
        hint = None
    return {"supported": supported, "unsupported": unsupported, "stale_hint": hint}


def _filter_hint(hint: str | None, facts: Any) -> str | None:
    if not hint:
        return None
    cleaned, _ = filter_numbers(hint, facts)
    cleaned = (cleaned or "").strip()
    return cleaned or None


def _cache_get(key: str) -> dict[str, Any] | None:
    import pearl_store  # noqa: PLC0415

    hit = pearl_store.kv_get(NS, key, TTL_S)
    val = (hit or {}).get("value")
    return val if isinstance(val, dict) and val.get("status") else None


def _cache_put(key: str, value: dict[str, Any]) -> None:
    import pearl_store  # noqa: PLC0415

    if value.get("status") == "unverifiable" and value.get("reason") in {
        "budget", "no-key", "llm-failed",
    }:
        return
    pearl_store.kv_put(NS, key, value)


def _card_truth(verdict: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": verdict.get("status") or "unverifiable",
        "checkedAt": verdict.get("checkedAt") or _now_iso(),
        "unsupported": list(verdict.get("unsupported") or []),
    }


async def judge(
    fiche: Any,
    extrait: str | None,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Ultra (tier judge) : {supported, unsupported, stale_hint}. Extrait vide → unverifiable."""
    extract = _clip_extract(extrait or "")
    if not extract:
        return unverifiable(reason="empty-extract")
    if not llm_budget.allow("judge"):
        return unverifiable(reason="budget")
    user = (
        "Fiche (faits, ne pas inventer de chiffre) :\n"
        f"{json.dumps(fiche, ensure_ascii=False, default=str)}\n\n"
        "Extrait de la page officielle :\n"
        f"{extract}\n\n"
        "Chaque affirmation de la fiche est-elle soutenue par l'extrait ?"
    )
    try:
        text, source = await cascade_text(
            SYSTEM, user, client, tier="judge", fallback="{}", facts=None,
        )
    except Exception as exc:
        log.debug("juge Ultra : %s", exc)
        return unverifiable(reason="llm-failed")
    if source == "budget":
        return unverifiable(reason="budget")
    parsed = _parse_verdict(text)
    if not parsed:
        return unverifiable(reason="llm-failed")
    facts = {"fiche": fiche, "extract": extract}
    parsed["stale_hint"] = _filter_hint(parsed.get("stale_hint"), facts)
    parsed["status"] = "verified"
    parsed["checkedAt"] = _now_iso()
    parsed["source"] = source
    return parsed


async def review_poe(
    fiche: dict[str, Any],
    zee: Any,
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Extract + juge, une fois par (ZEE, URL) et par 7 jours."""
    key = cache_key(zee, url)
    hit = _cache_get(key)
    if hit:
        return hit
    if not llm_budget.allow("judge"):
        return unverifiable(reason="budget")
    if not tavily_client.api_key():
        return unverifiable(reason="no-key")

    async with _inflight(key) as (wait, fut):
        if wait:
            return await fut
        try:
            cached = _cache_get(key)
            if cached:
                result = cached
            else:
                extracted = await tavily_client.extract([url], depth="basic", client=client)
                result = await judge(fiche, extracted.get("text") or "", client=client)
                _cache_put(key, result)
            if fut is not None and not fut.done():
                fut.set_result(result)
            return result
        except Exception as exc:
            if fut is not None and not fut.done():
                fut.set_exception(exc)
            raise


class _inflight:
    def __init__(self, key: str):
        self.key = key
        self.fut: asyncio.Future | None = None
        self.wait = False

    async def __aenter__(self):
        existing = _INFLIGHT.get(self.key)
        if existing is not None:
            self.wait = True
            self.fut = existing
            return True, existing
        loop = asyncio.get_running_loop()
        self.fut = loop.create_future()
        _INFLIGHT[self.key] = self.fut
        return False, self.fut

    async def __aexit__(self, exc_type, exc, tb):
        if not self.wait and _INFLIGHT.get(self.key) is self.fut:
            _INFLIGHT.pop(self.key, None)
        return False


def _poe_url(item: dict[str, Any]) -> str | None:
    raw = item.get("url") or item.get("visit_url")
    if isinstance(raw, str) and (raw.startswith("http://") or raw.startswith("https://")):
        return raw
    return None


def judge_enabled() -> bool:
    """Juge de vérité (Tavily lit la page officielle, Nemotron Ultra juge). ÉTEINT par défaut depuis le 28 sept.
    (décision du porteur) : depuis R8c le badge n'est plus rendu, on calculait et payait pour rien de visible.
    `NAVIGUIDE_TRUTH_JUDGE=1` le rallume (le module est gardé pour un retour du badge dans le panneau « ici »)."""
    return (os.environ.get("NAVIGUIDE_TRUTH_JUDGE") or "0").strip() in ("1", "true", "yes", "on")


async def maybe_attach(dossier: dict[str, Any], client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Déclencheur : ZEE Gold / fiche PoE avec URL officielle. Attache `truth` aux PoE — si le juge est allumé."""
    if not judge_enabled():
        return dossier
    zee = dossier.get("zee") if isinstance(dossier, dict) else None
    poes = list((dossier.get("poe") or []) if isinstance(dossier, dict) else [])
    if not poes:
        return dossier
    gold = bool(isinstance(zee, dict) and zee.get("gold"))
    if not gold and not any(_poe_url(p) for p in poes if isinstance(p, dict)):
        return dossier
    for item in poes:
        if not isinstance(item, dict):
            continue
        url = _poe_url(item)
        if not url:
            continue
        try:
            verdict = await review_poe(item, zee, url, client=client)
        except Exception as exc:
            log.debug("juge PoE %s : %s", url, exc)
            verdict = unverifiable(reason="llm-failed")
        item["truth"] = _card_truth(verdict)
    return dossier
