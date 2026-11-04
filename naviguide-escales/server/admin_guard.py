"""Sécurité P0 — un secret admin partagé et un limiteur de débit en mémoire.

Décision du porteur (18 sept. 2026) : secret partagé maintenant, vrai compte
plus tard. Le secret vit dans ~/.config/naviguide/simulator.env
(NAVIGUIDE_ADMIN_SECRET) ; le client l'envoie dans l'en-tête X-Naviguide-Admin.

Règle « fermé par défaut » : sans secret configuré, une écriture n'est
acceptée que d'un appel local direct (dev sur le Mac). Derrière nginx, les
en-têtes X-Real-IP / X-Forwarded-For sont présents → refus 503 tant que le
secret n'est pas posé, jamais une ouverture silencieuse.
"""
from __future__ import annotations

import hmac
import logging
import os
import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, Optional

from fastapi import HTTPException, Request

log = logging.getLogger("naviguide-simulator.guard")

ADMIN_HEADER = "X-Naviguide-Admin"
ADMIN_ENV = "NAVIGUIDE_ADMIN_SECRET"
_warned = False


def admin_secret() -> str:
    return (os.environ.get(ADMIN_ENV) or "").strip()


def client_ip(request: Request) -> str:
    """IP vue par nginx (X-Real-IP), sinon premier saut X-Forwarded-For, sinon socket."""
    real = (request.headers.get("x-real-ip") or "").strip()
    if real:
        return real
    fwd = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if fwd:
        return fwd
    return (request.client.host if request.client else "") or "unknown"


def _is_direct_local(request: Request) -> bool:
    if request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for"):
        return False
    host = (request.client.host if request.client else "") or ""
    return host in ("127.0.0.1", "::1", "localhost", "testclient")


def is_admin(request: Request) -> bool:
    secret = admin_secret()
    given = (request.headers.get(ADMIN_HEADER) or "").strip()
    if secret:
        return bool(given) and hmac.compare_digest(given, secret)
    return _is_direct_local(request)


def require_admin(request: Request) -> None:
    """Dépendance FastAPI : 401 sans le bon secret ; 503 si aucun secret derrière un proxy."""
    global _warned
    secret = admin_secret()
    if not secret:
        if _is_direct_local(request):
            if not _warned:
                log.warning("%s absent : écritures admin acceptées en local seulement", ADMIN_ENV)
                _warned = True
            return
        raise HTTPException(503, "secret admin non configuré sur le serveur")
    given = (request.headers.get(ADMIN_HEADER) or "").strip()
    if not given or not hmac.compare_digest(given, secret):
        raise HTTPException(401, "clé admin requise")


class RateLimiter:
    """Fenêtre glissante par clé (IP). `limit` appels par `window_s` secondes."""

    def __init__(self, limit: int, window_s: float, *, global_limit: Optional[int] = None) -> None:
        self.limit = int(limit)
        self.window_s = float(window_s)
        self.global_limit = global_limit
        self._hits: Dict[str, Deque[float]] = {}
        self._all: Deque[float] = deque()
        self._lock = threading.Lock()

    def _prune(self, q: Deque[float], now: float) -> None:
        cutoff = now - self.window_s
        while q and q[0] <= cutoff:
            q.popleft()

    def allow(self, key: str, now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            if self.global_limit is not None:
                self._prune(self._all, now)
                if len(self._all) >= self.global_limit:
                    return False
            q = self._hits.setdefault(key, deque())
            self._prune(q, now)
            if len(q) >= self.limit:
                return False
            q.append(now)
            if self.global_limit is not None:
                self._all.append(now)
            if len(self._hits) > 5000:  # forget idle keys
                for k in [k for k, v in self._hits.items() if not v]:
                    self._hits.pop(k, None)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._all.clear()


_LIMITERS: Dict[str, RateLimiter] = {}


def limiter(name: str, limit: int, window_s: float, *, global_limit: Optional[int] = None) -> RateLimiter:
    lim = _LIMITERS.get(name)
    if lim is None:
        lim = RateLimiter(limit, window_s, global_limit=global_limit)
        _LIMITERS[name] = lim
    return lim


def reset_limiters() -> None:
    for lim in _LIMITERS.values():
        lim.reset()


def rate_limited(name: str, limit: int, window_s: float, *, global_limit: Optional[int] = None) -> Callable:
    """Dépendance FastAPI : 429 au-delà de `limit` appels / IP / fenêtre (admin exempté)."""
    lim = limiter(name, limit, window_s, global_limit=global_limit)

    def dep(request: Request) -> None:
        if is_admin(request):
            return
        if not lim.allow(client_ip(request)):
            raise HTTPException(
                429,
                "trop de requêtes — réessayez dans une minute",
                headers={"Retry-After": str(int(window_s))},
            )

    return dep


def cors_origins() -> list[str]:
    """Origines autorisées (NAVIGUIDE_CORS_ORIGINS, virgules). En prod le client est
    servi par le même nginx : CORS ne sert qu'au dev Vite et aux outils."""
    raw = os.environ.get("NAVIGUIDE_CORS_ORIGINS")
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return [
        "https://naviguide.fr",
        "https://www.naviguide.fr",
        "https://simulator.naviguide.fr",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
