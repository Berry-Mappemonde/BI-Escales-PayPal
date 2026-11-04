"""Client Tavily — extract et search, jamais depuis le navigateur.

Un appel HTTP = 1 crédit, compté dans `llm_budget.record_tavily`.
Clé : `TAVILY_API_KEY` (VPS / .env local). Pas de clé → aucun réseau.
"""
from __future__ import annotations

import os
from typing import Any, Iterable

import httpx

import llm_budget

# Lié au chargement : les tests remplacent `httpx` du module par un faux.
_ReadTimeout = httpx.ReadTimeout

DEFAULT_BASE = "https://api.tavily.com"
TIMEOUT = httpx.Timeout(20.0, connect=8.0)


def api_base() -> str:
    return (os.environ.get("TAVILY_API_BASE") or DEFAULT_BASE).rstrip("/")


def api_key() -> str:
    return (os.environ.get("TAVILY_API_KEY") or "").strip()


def _headers(key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _urls(urls: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    for raw in urls or []:
        u = str(raw or "").strip()
        if u.startswith("http://") or u.startswith("https://"):
            out.append(u)
    return out


async def extract(
    urls: Iterable[str] | None,
    depth: str = "basic",
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """POST /extract. `depth` → `extract_depth` (basic | advanced)."""
    wanted = _urls(urls)
    empty = {"text": "", "results": [], "failed": [], "credits": 0}
    if not wanted:
        return empty
    import offline
    if offline.enabled():
        return empty
    key = api_key()
    if not key:
        return empty
    payload = {
        "urls": wanted,
        "extract_depth": (depth or "basic").strip() or "basic",
    }
    own = client is None
    http = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        r = await http.post(f"{api_base()}/extract", headers=_headers(key), json=payload)
    finally:
        if own:
            await http.aclose()
    llm_budget.record_tavily(1)
    data: dict[str, Any] = {}
    try:
        parsed = r.json()
        if isinstance(parsed, dict):
            data = parsed
    except Exception:
        data = {}
    results = data.get("results") if isinstance(data.get("results"), list) else []
    failed = data.get("failed_results") if isinstance(data.get("failed_results"), list) else []
    chunks: list[str] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        raw = item.get("raw_content") or item.get("content") or ""
        if isinstance(raw, str) and raw.strip():
            chunks.append(raw.strip())
    return {
        "text": "\n\n".join(chunks),
        "results": results,
        "failed": failed,
        "credits": 1,
        "status": r.status_code,
    }


async def search(
    query: str,
    topic: str | None = None,
    days: int | None = None,
    max_results: int | None = None,
    include_domains: Iterable[str] | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """POST /search (veille L4 : topic=news, 7 jours, 5 résultats)."""
    q = (query or "").strip()
    empty = {"results": [], "credits": 0}
    if not q:
        return empty
    import offline
    if offline.enabled():
        return empty
    key = api_key()
    if not key:
        return empty
    payload: dict[str, Any] = {"query": q}
    if topic:
        payload["topic"] = str(topic)
    if days is not None:
        payload["days"] = int(days)
    if max_results is not None:
        payload["max_results"] = int(max_results)
    domains = [str(d).strip() for d in (include_domains or []) if str(d).strip()]
    if domains:
        payload["include_domains"] = domains
    own = client is None
    http = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        r = await http.post(f"{api_base()}/search", headers=_headers(key), json=payload)
    except _ReadTimeout:
        # Requête partie, réponse jamais lue : Tavily l'a sans doute facturée.
        # Le succès compte plus bas, donc pas de double décompte.
        llm_budget.record_tavily(1)
        raise
    finally:
        if own:
            await http.aclose()
    llm_budget.record_tavily(1)
    data: dict[str, Any] = {}
    try:
        parsed = r.json()
        if isinstance(parsed, dict):
            data = parsed
    except Exception:
        data = {}
    results = data.get("results") if isinstance(data.get("results"), list) else []
    return {
        "results": results,
        "credits": 1,
        "status": r.status_code,
    }
