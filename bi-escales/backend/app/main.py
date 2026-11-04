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


_TRUTHY = {"1", "true", "yes", "on"}

_escales_on = os.environ.get("ESCALES_ENABLED", "").strip().lower() in _TRUTHY
if _escales_on:
    from app.routers import escales

    app.include_router(escales.router)
    app.include_router(escales.webhooks_router)

    if os.environ.get("ESCALES_PAYPAL_MOCK", "").strip().lower() in _TRUTHY:

        @app.on_event("startup")
        async def _install_demo_paypal() -> None:
            from app.demo_seed import ensure_demo_milestones
            from app.escales.paypal_demo_client import demo_client_factory
            from app.routers.escales import set_paypal_client_factory

            await ensure_demo_milestones()
            set_paypal_client_factory(demo_client_factory)
