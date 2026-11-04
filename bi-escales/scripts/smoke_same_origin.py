"""Contrôle local du service unique. Ne contacte pas Render et ne déploie pas.

Adapté de bi-escales/render.yaml et de bi-escales/docs/deploiement-render.md
(le site statique de hackathon/minimix-frontend est retiré).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_ORIGIN = "https://bi-escales-api.onrender.com"
RETURN_URL = f"{API_ORIGIN}/?paypal=return"
CANCEL_URL = f"{API_ORIGIN}/?paypal=cancel"


def check_blueprint() -> list[str]:
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    problems = []
    if text.count("type: web") != 1:
        problems.append("render.yaml doit déclarer un seul service web")
    if "runtime: static" in text or "type: static" in text:
        problems.append("le site statique est encore dans le blueprint")
    if "autoDeployTrigger: off" not in text:
        problems.append("autoDeployTrigger doit être off")
    if "plan: free" not in text:
        problems.append("le plan doit rester free")
    if f"value: {RETURN_URL}" not in text:
        problems.append("ESCALES_RETURN_URL du blueprint ne vise pas le service API")
    if f"value: {CANCEL_URL}" not in text:
        problems.append("ESCALES_CANCEL_URL du blueprint ne vise pas le service API")
    if "https://bi-escales.onrender.com" in text:
        problems.append("l'hôte statique 404 est encore cité")
    if "npm run build" not in text:
        problems.append("le build doit produire le frontend")
    main = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    if "frontend/dist" not in main or "attach_frontend" not in main:
        problems.append("FastAPI ne sert pas frontend/dist")
    return problems


def check_defaults() -> list[str]:
    backend = ROOT / "backend"
    sys.path.insert(0, str(backend))
    from app.escales.config import order_cancel_url, order_return_url

    problems = []
    for name in ("ESCALES_RETURN_URL", "ESCALES_CANCEL_URL"):
        # The import reads the process env. Drop overrides so the default shows.
        import os

        os.environ.pop(name, None)
    if order_return_url() != RETURN_URL:
        problems.append(f"défaut return {order_return_url()!r}")
    if order_cancel_url() != CANCEL_URL:
        problems.append(f"défaut cancel {order_cancel_url()!r}")
    return problems


def main() -> int:
    problems = check_blueprint() + check_defaults()
    if problems:
        print("\n".join(problems))
        return 1
    print("same-origin ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
