"""Onboard-after-payment routes (sandbox, feature-flagged)."""

from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from starlette.responses import JSONResponse

from app.escales.config import (
    email_enabled,
    escales_enabled,
    onboard_after_payment_enabled,
    platform_credentials_active,
)
from app.escales.paypal_client import PayPalClient, PayPalError
from app.escales.rate_limit import RateLimited, client_ip, hit
from app.escales.webhooks import WebhookRejected
from app.project_onboarding.constants import DEMO_PROJECT_ID
from app.project_onboarding.seed import seed_demo_onboarding
from app.project_onboarding import service
from app.project_onboarding.webhooks import onboarding_webhook_config, verify_merchant_onboarding_webhook

router = APIRouter(prefix="/api/escales/project-onboarding", tags=["project-onboarding"])
webhooks_router = APIRouter(prefix="/api/escales/project-onboarding", tags=["project-onboarding-webhooks"])


def _require_escales() -> None:
    if not escales_enabled():
        raise HTTPException(status_code=404, detail="Not Found")


def _require_feature() -> None:
    _require_escales()
    if not onboard_after_payment_enabled():
        raise HTTPException(status_code=404, detail="Not Found")


def _require_admin(request: Request) -> None:
    try:
        expected = os.environ["ESCALES_ADMIN_KEY"]
    except KeyError:
        raise HTTPException(status_code=401, detail="ESCALES_ADMIN_KEY is not configured") from None
    provided = request.headers.get("x-admin-key", "")
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Admin key required")


def _lang(request: Request) -> str:
    accept = request.headers.get("accept-language", "fr")
    token = accept.split(",")[0].strip().lower()
    return "en" if token.startswith("en") else "fr"


def _paypal_client() -> PayPalClient:
    """Client that verifies the merchant-onboarding webhook.

    The PayPal Platform app when its webhook id is configured; otherwise the main
    app, which owns the existing webhook id (see ``onboarding_webhook_config``).
    """
    return PayPalClient(onboarding_webhook_config())


def _enforce_capture_rate(request: Request) -> None:
    forwarded = request.headers.get("x-forwarded-for", "")
    host = request.client.host if request.client else ""
    try:
        hit(client_ip(forwarded, host))
    except RateLimited as exc:
        raise HTTPException(
            status_code=429,
            detail="Too many capture requests",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc


@router.get("/status")
async def feature_status():
    _require_escales()
    return {
        "enabled": onboard_after_payment_enabled(),
        "email_enabled": email_enabled(),
        "demo_project_id": DEMO_PROJECT_ID,
        # A boolean only: never the client id, the secret or a webhook id.
        "platform_credentials": platform_credentials_active(),
    }


@router.post("/seed")
async def post_seed(request: Request):
    _require_feature()
    _require_admin(request)
    payload = await seed_demo_onboarding()
    return payload


@router.get("/projects/{project_id}")
async def get_project_status(project_id: str, request: Request):
    _require_feature()
    view = await service.public_project_view(project_id, lang=_lang(request))
    if not view:
        raise HTTPException(status_code=404, detail="project not found")
    return view


@router.post("/projects/{project_id}/donations")
async def post_donation(project_id: str, body: dict, request: Request):
    _require_feature()
    try:
        saved = await service.create_donation_order(
            project_id,
            amount_eur=str(body.get("amount_eur") or ""),
            contributor=str(body.get("contributor") or ""),
            lang=str(body.get("lang") or _lang(request)),
            return_url=str(body.get("return_url") or ""),
            cancel_url=str(body.get("cancel_url") or ""),
        )
    except PermissionError:
        raise HTTPException(status_code=404, detail="Not Found") from None
    except LookupError:
        raise HTTPException(status_code=404, detail="project not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PayPalError as exc:
        raise HTTPException(status_code=exc.status, detail="PayPal error") from exc
    return saved


@router.post("/donations/{donation_id}/capture")
async def post_capture(donation_id: str, request: Request):
    _require_feature()
    _enforce_capture_rate(request)
    try:
        return await service.finalize_donation_capture(donation_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="donation not found") from None
    except service.DonationCaptureRejected as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    except PayPalError as exc:
        raise HTTPException(status_code=exc.status, detail="PayPal error") from exc


@router.post("/projects/{project_id}/onboarding-link")
async def post_onboarding_link(project_id: str, request: Request):
    _require_feature()
    try:
        return await service.ensure_onboarding_link(project_id, lang=_lang(request))
    except LookupError:
        raise HTTPException(status_code=404, detail="project not found") from None
    except PayPalError as exc:
        raise HTTPException(status_code=exc.status, detail="PayPal error") from exc


@router.get("/projects/{project_id}/onboarding-link/copy")
async def get_copy_link(project_id: str, request: Request):
    _require_feature()
    _require_admin(request)
    try:
        referral = await service.refresh_action_url(project_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="referral not found") from None
    except PayPalError as exc:
        raise HTTPException(status_code=exc.status, detail="PayPal error") from exc
    return {"action_url": referral.get("action_url"), "project_id": project_id}


@router.get("/projects/{project_id}/email/preview", response_class=HTMLResponse)
async def get_email_preview(project_id: str, request: Request, donation_id: str = ""):
    _require_feature()
    try:
        preview = await service.email_preview(project_id, lang=_lang(request), donation_id=donation_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="project not found") from None
    except PayPalError as exc:
        raise HTTPException(status_code=exc.status, detail="PayPal error") from exc
    if request.query_params.get("format") == "json":
        return JSONResponse(preview)
    return HTMLResponse(preview["html"])


@router.post("/projects/{project_id}/email/send")
async def post_email_send(project_id: str, request: Request, donation_id: str = ""):
    _require_feature()
    _require_admin(request)
    try:
        return await service.send_onboarding_email(project_id, lang=_lang(request), donation_id=donation_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="project not found") from None
    except PayPalError as exc:
        raise HTTPException(status_code=exc.status, detail="PayPal error") from exc


def _friendly_onboarding_return() -> HTMLResponse:
    """A seller who lands here before PayPal adds its return parameters sees a page, not JSON."""
    return HTMLResponse(
        """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>PayPal seller return</title></head>
<body>
<p>PayPal has not sent the seller return yet. Finish seller setup in the PayPal sandbox, then come back.</p>
<p>PayPal n'a pas encore renvoyé le vendeur. Terminez l'inscription dans le bac à sable PayPal, puis revenez.</p>
<p><a href="/">BI Escales</a></p>
</body>
</html>"""
    )


@router.get("/projects/{project_id}/onboarding/return")
async def get_onboarding_return(
    project_id: str,
    merchantIdInPayPal: str = "",
    permissionsGranted: str = "",
    isEmailConfirmed: str = "",
):
    _require_feature()
    if not any(str(value or "").strip() for value in (merchantIdInPayPal, permissionsGranted, isEmailConfirmed)):
        return _friendly_onboarding_return()
    perms = str(permissionsGranted or "").strip().lower() in {"1", "true", "yes"}
    email_ok = str(isEmailConfirmed or "").strip().lower() in {"1", "true", "yes"}
    try:
        return await service.handle_onboarding_return(
            project_id,
            merchant_id_in_paypal=merchantIdInPayPal,
            permissions_granted=perms,
            is_email_confirmed=email_ok,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="project not found") from None
    except PayPalError as exc:
        raise HTTPException(status_code=exc.status, detail="PayPal error") from exc


@webhooks_router.post("/webhooks/paypal-merchant")
async def post_merchant_webhook(request: Request):
    _require_feature()
    raw = await request.body()
    try:
        return await verify_merchant_onboarding_webhook(
            raw_body=raw,
            headers=request.headers,
            client=_paypal_client(),
        )
    except WebhookRejected as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
