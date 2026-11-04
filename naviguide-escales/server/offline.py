"""Mode hors ligne : stock figé, aucun appel HTTP sortant.

Lu au démarrage (`NAVIGUIDE_OFFLINE=1`) : hindcast coupé, prévision
synthétique, atlas / Tavily / LLM / Copernicus en repli, et toute tentative
HTTP non locale lève `OfflineError` (journalisée).
"""
from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

log = logging.getLogger("naviguide-simulator.offline")

_TRUTHY = ("1", "true", "yes")
_GUARD_INSTALLED = False


class OfflineError(RuntimeError):
    """HTTP sortant interdit tant que NAVIGUIDE_OFFLINE=1."""


def enabled() -> bool:
    return (os.environ.get("NAVIGUIDE_OFFLINE") or "").strip().lower() in _TRUTHY


def is_local_url(url: object) -> bool:
    try:
        parsed = urlparse(str(url))
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return True
    return host in ("127.0.0.1", "localhost", "::1") or host.endswith(".localhost")


def deny_outgoing(url: object) -> None:
    if not enabled():
        return
    if is_local_url(url):
        return
    log.error("NAVIGUIDE_OFFLINE=1 : HTTP sortant interdit %s", url)
    raise OfflineError(f"NAVIGUIDE_OFFLINE=1 : HTTP sortant interdit ({url})")


def apply_at_startup() -> None:
    """Coupe les fournisseurs externes et pose le garde HTTP."""
    if not enabled():
        return
    os.environ["NAVIGUIDE_HINDCAST"] = "0"
    os.environ["NAVIGUIDE_FORECAST_BACKEND"] = "synthetic"
    os.environ.setdefault("NAVIGUIDE_OFFICIAL_WORKER", "0")
    os.environ.setdefault("NAVIGUIDE_ICI_WARM", "0")
    os.environ.setdefault("NAVIGUIDE_ZEE_LOCAL", "0")
    install_http_guard()
    log.info("mode hors ligne : stock figé, aucun fournisseur externe")


def install_http_guard() -> None:
    """Patche httpx : un GET/POST hors localhost lève OfflineError."""
    global _GUARD_INSTALLED
    if _GUARD_INSTALLED:
        return
    import httpx

    orig_async = httpx.AsyncClient.request
    orig_sync = httpx.Client.request

    async def async_request(self, method, url, *args, **kwargs):
        deny_outgoing(url)
        return await orig_async(self, method, url, *args, **kwargs)

    def sync_request(self, method, url, *args, **kwargs):
        deny_outgoing(url)
        return orig_sync(self, method, url, *args, **kwargs)

    httpx.AsyncClient.request = async_request  # type: ignore[method-assign]
    httpx.Client.request = sync_request  # type: ignore[method-assign]
    _GUARD_INSTALLED = True
