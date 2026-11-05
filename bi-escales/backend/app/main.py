"""Standalone entry point for BI Escales (python -m uvicorn app.main:app)."""
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from app.bi_marinas_catalog import build_escale_fiche
from app.bi_projects_catalog import get_bi_projects_geojson
from app.escales.config import cors_origins

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


@app.get("/api/health")
def health():
    return {"status": "ok"}


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


_escales_on = os.environ.get("ESCALES_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
if _escales_on:
    from app.routers import escales

    app.include_router(escales.router)
    app.include_router(escales.webhooks_router)


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

    @application.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (dist / full_path).resolve() if full_path else index
        if full_path and candidate.is_file() and str(candidate).startswith(str(dist)):
            return FileResponse(candidate)
        return FileResponse(index)


attach_frontend(app)
