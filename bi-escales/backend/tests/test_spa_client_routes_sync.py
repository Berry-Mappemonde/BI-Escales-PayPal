"""Keep backend SPA route list aligned with frontend clientRoutes.ts."""
from __future__ import annotations

import re
from pathlib import Path

from app.spa_client_routes import KNOWN_CLIENT_ROUTES, normalize_client_path


def _frontend_client_routes() -> set[str]:
    ts_path = Path(__file__).resolve().parents[2] / "frontend" / "src" / "routes" / "clientRoutes.ts"
    text = ts_path.read_text(encoding="utf-8")
    paths = re.findall(r'"(/[^"]*)"', text)
    return {normalize_client_path(p.lstrip("/")) for p in paths}


def test_spa_client_routes_match_frontend_manifest():
    frontend = _frontend_client_routes()
    backend = set(KNOWN_CLIENT_ROUTES)
    assert frontend == backend, f"frontend {frontend} vs backend {backend}"
