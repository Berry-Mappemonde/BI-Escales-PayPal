"""Standalone entry point for BI Escales (python -m uvicorn app.main:app)."""
import os
import re
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse, RedirectResponse, Response

from app.bi_marinas_catalog import build_escale_fiche, get_all_escale_marinas_geojson, get_escale_marinas_geojson
from app.bi_projects_catalog import BROWSER_MAX_AGE, get_bi_projects_geojson, projects_geojson_body
from app.escales.config import cors_origins, resolve_apple_pay_domain_association_path
from app.middleware.security_headers import install_security_headers
from app.spa_client_routes import page_head

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
async def bi_projects_geojson(request: Request):
    """The projects of the map and the list: about 3 MB of JSON, the same for minutes.

    Encoded once per catalogue refresh, and sent with an ETag and a short max-age so a
    reload reuses the browser's copy (304, or no request at all) instead of downloading it again.
    """
    payload = await get_bi_projects_geojson()
    body, etag = projects_geojson_body(payload)
    headers = {"Cache-Control": f"public, max-age={BROWSER_MAX_AGE}", "ETag": etag}
    asked = {tag.strip() for tag in (request.headers.get("if-none-match") or "").split(",")}
    if etag in asked or f"W/{etag}" in asked:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/geo+json", headers=headers)


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


_backend_static = Path(__file__).resolve().parent.parent / "static"
_onboarding_static = _backend_static / "onboarding"
if _onboarding_static.is_dir():
    app.mount("/static/onboarding", StaticFiles(directory=_onboarding_static), name="onboarding-static")

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


# Same paths as frontend/src/Root.tsx. Anything else that is not a built file goes to the map.
_SPA_EXACT = {"escales/wishlists"}
_ONBOARDING_PATH = re.compile(r"^projects/[^/]+/onboarding(?:/return)?$")
_REDIRECT_STATUS = 302


def is_known_spa_path(full_path: str) -> bool:
    path = full_path.strip("/")
    if not path:
        return True
    return path in _SPA_EXACT or _ONBOARDING_PATH.fullmatch(path) is not None


def _query_suffix(query: list[tuple[str, str]], *, lang: str | None = None) -> str:
    pairs = [(key, value) for key, value in query if lang is None or key != "lang"]
    if lang:
        pairs.append(("lang", lang))
    if not pairs:
        return ""
    return "?" + urlencode(pairs)


def language_or_unknown_redirect(full_path: str, query: list[tuple[str, str]]) -> str | None:
    """`/en` and `/fr` become the same path with `?lang=`. Unknown paths go to `/`.

    Known client routes (Root.tsx) are served as the app. The redirect is temporary
    so a wrong target is not cached in a judge's browser.
    """
    head, _, rest = full_path.partition("/")
    if head in {"en", "fr"}:
        target = "/" + rest.replace("\\", "/").lstrip("/")
        return target + _query_suffix(query, lang=head)
    if is_known_spa_path(full_path):
        return None
    if full_path:
        return "/" + _query_suffix(query)
    return None


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
    def spa(full_path: str, request: Request):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        if "\\" in full_path and not full_path.startswith(("en/", "fr/")):
            raise HTTPException(status_code=404)
        candidate = (dist / full_path).resolve() if full_path else index
        if full_path and candidate.is_file() and str(candidate).startswith(str(dist)):
            return FileResponse(candidate)
        # Old /en and /fr links and unknown paths: Codex's redirects (#272), none answers 404.
        target = language_or_unknown_redirect(full_path, list(request.query_params.multi_items()))
        if target is not None:
            return RedirectResponse(url=target, status_code=_REDIRECT_STATUS)
        # The page, with this page's own canonical address and language alternates.
        return HTMLResponse(page_head(index.read_text(encoding="utf-8"), full_path, request.url.query, image_origin=str(request.base_url)))


attach_frontend(app)
