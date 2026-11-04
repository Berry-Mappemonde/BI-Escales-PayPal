"""Standalone entry point for BI Escales (python -m uvicorn app.main:app)."""
import os

from fastapi import FastAPI

app = FastAPI(title="BI Escales — Pay Only If We Sail")


@app.get("/api/health")
def health():
    return {"status": "ok"}


_escales_on = os.environ.get("ESCALES_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
if _escales_on:
    from app.routers import escales

    app.include_router(escales.router)
