"""Standalone entry point for BI Escales (python -m uvicorn app.main:app)."""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.escales.config import cors_origins

app = FastAPI(title="BI Escales — Pay Only If We Sail")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Accept", "Accept-Language", "Content-Type", "PayPal-Request-Id", "x-admin-key"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


_escales_on = os.environ.get("ESCALES_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
if _escales_on:
    from app.routers import escales

    app.include_router(escales.router)
    app.include_router(escales.webhooks_router)
