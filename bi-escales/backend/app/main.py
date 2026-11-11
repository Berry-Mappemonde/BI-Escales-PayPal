"""Standalone entry point for BI Escales (python -m uvicorn app.main:app)."""
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from app.bi_marinas_catalog import build_escale_fiche, get_all_escale_marinas_geojson, get_escale_marinas_geojson
from app.bi_projects_catalog import get_bi_projects_geojson
from app.escales.config import cors_origins, resolve_apple_pay_domain_association_path
from app.middleware.security_headers import install_security_headers

app = FastAPI(title="BI Escales — Pay Only If We Sail")


def install_cors(application: FastAPI) -> None:
    """Cross-origin access from ``ESCALES_CORS_ORIGINS`` only (empty → none)."""
    application.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Accept", "Accept-Language", "Content-Type", "PayPal-Request-Id", "x-admin-key"],
    )


def _log_nim_ids() -> None:
    """Ids only. A missing LLM module must not stop the API."""
    try:
        from app.core.llm import log_effective_nim_models

        log_effective_nim_models()
    except Exception:
        return


_log_nim_ids()
install_cors(app)
install_security_headers(app)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/.well-known/apple-developer-merchantid-domain-association", include_in_schema=False)
def apple_pay_domain_association():
    """Apple Pay domain verification for PayPal sandbox (bi-escales-api-test2.onrender.com)."""
    candidate = resolve_apple_pay_domain_association_path()
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="apple pay domain file missing")
    return FileResponse(candidate, media_type="application/octet-stream")


@app.get("/bi-projects.geojson", include_in_schema=False)
async def bi_projects_geojson():
    payload = await get_bi_projects_geojson()
    return JSONResponse(content=payload, media_type="application/geo+json")


@app.get("/api/escale-fiche", include_in_schema=False)
async def escale_fiche(name: str = ""):
    stop_name = (name or "").strip()
    if not stop_name:
        raise HTTPException(status_code=400, detail="name required")
    payload = await build_escale_fiche(stop_name)
    return JSONResponse(content=payload)


@app.get("/api/escale-marinas.geojson", include_in_schema=False)
async def escale_marinas_geojson(name: str = ""):
    stop_name = (name or "").strip()
    if not stop_name:
        payload = await get_all_escale_marinas_geojson()
    else:
        payload = await get_escale_marinas_geojson(stop_name)
    return JSONResponse(content=payload, media_type="application/geo+json")


_escales_on = os.environ.get("ESCALES_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
if _escales_on:
    from app.routers import escales, escales_demo, project_onboarding

    app.include_router(escales.router)
    app.include_router(escales.webhooks_router)
    app.include_router(escales_demo.router)
    app.include_router(project_onboarding.router)
    app.include_router(project_onboarding.webhooks_router)

    from app.escales.config import warn_if_platform_credentials_missing

    warn_if_platform_credentials_missing()


def frontend_dist() -> Path:
    """Built Vite app, next to the backend (bi-escales/frontend/dist)."""
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


def attach_frontend(application: FastAPI) -> None:
    """Serve the built page from this process. Absent dist leaves the API alone."""
    dist = frontend_dist().resolve()
    index = dist / "index.html"
    if not index.is_file():
        return
    assets = dist / "assets"
    if assets.is_dir():
        application.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

    @application.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (dist / full_path).resolve() if full_path else index
        if full_path and candidate.is_file() and str(candidate).startswith(str(dist)):
            return FileResponse(candidate)
        return FileResponse(index)


attach_frontend(app)
