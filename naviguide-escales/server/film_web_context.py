"""Contexte web Tavily du film rédigé (Revoir → Rédigé).

Au clic Rédigé seulement (jamais au GET) : une recherche Tavily sur le dernier
port atteint par le film, via `port_web_context.fetch_port_web` (même cache
`pearl_store` de 24 h et même plafond de crédits que le chat journal). On ne
garde que la provenance publique — port, date, titres et URLs —, jamais
d'extrait recopié dans le texte du film : rien n'est inventé ni réécrit.

Sans clé, plafond, erreur ou résultat vide : `None`, et le film ne montre rien.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

import port_web_context

BASIS = "tavily"
MAX_SOURCES = 3


def _domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _normalize_url_key(url: str) -> str:
    """Clé de dédoublonnage : schéma/hôte en minuscules, sans www., sans / final ni fragment."""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = p.path or ""
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    scheme = (p.scheme or "http").lower()
    port = f":{p.port}" if p.port is not None else ""
    return f"{scheme}://{host}{port}{path}{'?' + p.query if p.query else ''}"


def _url_has_host(url: str) -> bool:
    return bool((urlparse(url).netloc or "").strip())


def compact(pw: Any) -> Optional[dict[str, Any]]:
    """Réponse `fetch_port_web` → provenance publique du film, ou None."""
    if not isinstance(pw, dict) or pw.get("status") != "ready":
        return None
    port = str(pw.get("port") or "").strip()
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in pw.get("sources") or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if not (url.startswith("https://") or url.startswith("http://")):
            continue
        if not _url_has_host(url):
            continue
        key = _normalize_url_key(url)
        if not key or key in seen:
            continue
        seen.add(key)
        domain = _domain(url)
        title = str(row.get("title") or "").strip() or domain
        sources.append({"title": title[:160], "url": url, "domain": domain})
        if len(sources) >= MAX_SOURCES:
            break
    if not port or not sources:
        return None
    return {
        "basis": BASIS,
        "port": port,
        "fetchedAt": pw.get("fetchedAt"),
        "sources": sources,
    }


def public(stored: Any) -> Optional[dict[str, Any]]:
    """Contexte rangé dans le snapshot du film → champ servi (revalidé)."""
    if not isinstance(stored, dict) or stored.get("basis") != BASIS:
        return None
    return compact({
        "status": "ready",
        "port": stored.get("port"),
        "fetchedAt": stored.get("fetchedAt"),
        "sources": stored.get("sources"),
    })


async def fetch_for_port(
    port: str,
    *,
    now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
) -> Optional[dict[str, Any]]:
    """Une recherche Tavily (cache 24 h, plafond du jour) sur le port du film."""
    label = (port or "").strip()
    if not label:
        return None
    pw = await port_web_context.fetch_port_web(label, now=now, client=client)
    return compact(pw)
