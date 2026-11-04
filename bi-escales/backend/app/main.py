"""Standalone entry point for BI Escales (python -m uvicorn app.main:app)."""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.escales.config import cors_origins

app = FastAPI(title="BI Escales — Pay Only If We Sail")


def install_cors(application: FastAPI) -> None:
    """Allow a front on another origin. Origins come from ESCALES_CORS_ORIGINS.

    Empty means no cross-origin access. The Vite dev server proxies ``/api``,
    so local demo does not need an entry. ``PayPal-Request-Id`` and
    ``x-admin-key`` trigger a preflight, so they are listed here.
    """
    application.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "PayPal-Request-Id", "x-admin-key"],
    )


install_cors(app)


@app.get("/api/health")
def health():
    return {"status": "ok"}


_escales_on = os.environ.get("ESCALES_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
if _escales_on:
    from app.routers import escales

    app.include_router(escales.router)
    app.include_router(escales.webhooks_router)
