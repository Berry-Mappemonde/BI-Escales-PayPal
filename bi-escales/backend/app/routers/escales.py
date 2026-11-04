"""BI Escales HTTP API, prefix /api/escales.

Registered from ``app.main`` only when ``ESCALES_ENABLED`` is truthy.
Every route also 404s when the flag is off, so a process that imported the
router early still hides it. Capture and void require ``x-admin-key``.
"""
from __future__ import annotations

import os
import secrets
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from starlette.responses import Response

from app.escales.captain import chat as captain_chat
from app.escales.captain import review as captain_review
from app.escales.config import (
    bryntum_scheduler_enabled,
    channel3_enabled,
    elastic_evidence_enabled,
    escales_enabled,
    kernel_evidence_enabled,
    load_config,
    naviguide_bridge_enabled,
    vault_enabled,
    webhooks_enabled,
)
from app.escales.ledger import get_ledger, list_finance_entries
from app.escales.milestones import list_milestones, record_evidence
from app.escales.naviguide_bridge import (
    escales_to_milestones,
    fetch_naviguide_export,
    sync_milestone_shells,
)
from app.escales.paypal_client import PayPalClient, PayPalError
from app.escales.pledges import (
    IllegalTransition,
    PledgeNotFound,
    authorize_pledge,
    capture_pledge,
    create_pledge,
    register_vault_pledge,
    require_pledge,
    resolve_payment_mode,
    to_public,
    void_pledge,
)
from app.escales.toolkit_tools import ReadOnlyTools
from app.escales.webhooks import WebhookDuplicate, WebhookRejected, verify_and_process

_client_factory: Optional[Callable[[], Any]] = None


def set_paypal_client_factory(factory: Optional[Callable[[], Any]]) -> None:
    """Tests inject a fake client. Production leaves this unset."""
    global _client_factory
    _client_factory = factory


class _EnabledRoute(APIRoute):
    def get_route_handler(self):
        inner = super().get_route_handler()

        async def guard(request: Request) -> Response:
            if not escales_enabled():
                raise HTTPException(status_code=404, detail="Not Found")
            return await inner(request)

        return guard


class _WebhooksRoute(APIRoute):
    def get_route_handler(self):
        inner = super().get_route_handler()

        async def guard(request: Request) -> Response:
            if not escales_enabled() or not webhooks_enabled():
                raise HTTPException(status_code=404, detail="Not Found")
            return await inner(request)

        return guard


router = APIRouter(prefix="/api/escales", route_class=_EnabledRoute, tags=["escales"])
webhooks_router = APIRouter(prefix="/api/escales", route_class=_WebhooksRoute, tags=["escales-webhooks"])


class PledgeIn(BaseModel):
    amount_eur: str
    description: str
    milestone_id: str
    contributor: Optional[str] = None


class EvidenceIn(BaseModel):
    met: Optional[bool] = None
    facts: dict = Field(default_factory=dict)


class ChatIn(BaseModel):
    message: str


class VaultRegisterIn(BaseModel):
    setup_token_id: Optional[str] = None


def _paypal() -> Any:
    if _client_factory is not None:
        return _client_factory()
    cfg = load_config()
    if not cfg.configured:
        raise HTTPException(status_code=503, detail="PayPal sandbox is not configured")
    return PayPalClient(cfg)


def _reader() -> Optional[ReadOnlyTools]:
    try:
        client = _paypal()
    except HTTPException:
        return None
    return ReadOnlyTools(client)


def _require_treasurer(request: Request) -> None:
    try:
        expected = os.environ["ESCALES_ADMIN_KEY"]
    except KeyError:
        raise HTTPException(status_code=401, detail="ESCALES_ADMIN_KEY is not configured") from None
    if not expected:
        raise HTTPException(status_code=401, detail="ESCALES_ADMIN_KEY is not configured")
    provided = request.headers.get("x-admin-key", "")
    if not provided:
        raise HTTPException(status_code=401, detail="Admin key required")
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Admin key rejected")


def _as_http(exc: Exception) -> HTTPException:
    if isinstance(exc, PledgeNotFound):
        return HTTPException(status_code=404, detail="Pledge not found")
    if isinstance(exc, IllegalTransition):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, PayPalError):
        return HTTPException(status_code=502, detail="PayPal request failed")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    raise exc


def _public_milestone(doc: dict) -> dict:
    return {
        "id": doc.get("_id"),
        "evidence": doc.get("evidence") or [],
        "proposal": doc.get("proposal"),
        "meta": doc.get("meta"),
        "updated_at": doc.get("updated_at"),
    }


@router.get("/features")
async def get_features():
    return {
        "naviguide_bridge": naviguide_bridge_enabled(),
        "elastic": elastic_evidence_enabled(),
        "kernel": kernel_evidence_enabled(),
        "channel3": channel3_enabled(),
        "bryntum": bryntum_scheduler_enabled(),
        "vault": vault_enabled(),
    }


@router.get("/schedule")
async def get_schedule():
    export = await fetch_naviguide_export()
    return {
        "export": export,
        "milestones": escales_to_milestones(export),
        "source": "naviguide" if naviguide_bridge_enabled() else "local",
    }


@router.post("/schedule/sync")
async def post_schedule_sync():
    docs = await sync_milestone_shells()
    return [_public_milestone(doc) for doc in docs]


@router.post("/pledges")
async def post_pledge(body: PledgeIn, request: Request):
    client_key = request.headers.get("paypal-request-id")
    try:
        mode = await resolve_payment_mode(body.milestone_id)
        doc = await create_pledge(
            amount_eur=body.amount_eur,
            description=body.description,
            milestone_id=body.milestone_id,
            contributor=body.contributor,
            client=_paypal(),
            client_key=client_key,
            payment_mode=mode,
        )
    except (PayPalError, ValueError) as exc:
        raise _as_http(exc) from exc
    public = to_public(doc)
    public["payment_mode"] = doc.get("payment_mode") or doc.get("intent")
    return public


@router.post("/pledges/{pledge_id}/vault")
async def post_register_vault(pledge_id: str, body: VaultRegisterIn):
    """Store the PayPal payment method after setup-token approval (no debit)."""
    if not vault_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    try:
        doc = await register_vault_pledge(
            pledge_id,
            _paypal(),
            setup_token_id=body.setup_token_id,
        )
    except (PledgeNotFound, IllegalTransition, PayPalError, ValueError) as exc:
        raise _as_http(exc) from exc
    public = to_public(doc)
    public["payment_mode"] = doc.get("payment_mode") or "VAULT"
    return public


@router.get("/pledges")
async def get_pledges(request: Request):
    """Treasurer queue. Not the browser's local id list."""
    _require_treasurer(request)
    docs = await get_ledger().list_pledges()
    return [to_public(doc) for doc in docs]


@router.get("/finance")
async def get_finance(request: Request):
    _require_treasurer(request)
    return await list_finance_entries()


@router.post("/pledges/{pledge_id}/authorize")
async def post_authorize(pledge_id: str):
    try:
        doc = await authorize_pledge(pledge_id, _paypal())
    except (PledgeNotFound, IllegalTransition, PayPalError, ValueError) as exc:
        raise _as_http(exc) from exc
    return to_public(doc)


@router.post("/pledges/{pledge_id}/capture")
async def post_capture(pledge_id: str, request: Request):
    _require_treasurer(request)
    try:
        doc = await capture_pledge(pledge_id, _paypal())
    except (PledgeNotFound, IllegalTransition, PayPalError, ValueError) as exc:
        raise _as_http(exc) from exc
    return to_public(doc)


@router.post("/pledges/{pledge_id}/void")
async def post_void(pledge_id: str, request: Request):
    _require_treasurer(request)
    try:
        doc = await void_pledge(pledge_id, _paypal())
    except (PledgeNotFound, IllegalTransition, PayPalError) as exc:
        raise _as_http(exc) from exc
    return to_public(doc)


@router.get("/pledges/{pledge_id}")
async def get_pledge(pledge_id: str):
    try:
        doc = await require_pledge(pledge_id)
    except PledgeNotFound as exc:
        raise _as_http(exc) from exc
    return to_public(doc)


@router.get("/milestones")
async def get_milestones():
    docs = await list_milestones()
    return [_public_milestone(doc) for doc in docs]


@router.post("/milestones/{milestone_id}/evidence")
async def post_evidence(milestone_id: str, body: EvidenceIn):
    try:
        evidence = await record_evidence(milestone_id, body.met, body.facts)
    except ValueError as exc:
        raise _as_http(exc) from exc
    return {"milestone_id": milestone_id, **evidence}


@router.post("/captain/review/{milestone_id}")
async def post_review(milestone_id: str):
    try:
        return await captain_review(milestone_id, reader=_reader())
    except (PayPalError, ValueError) as exc:
        raise _as_http(exc) from exc


@router.post("/captain/chat")
async def post_chat(body: ChatIn):
    try:
        return await captain_chat(body.message)
    except ValueError as exc:
        raise _as_http(exc) from exc


@webhooks_router.post("/webhooks/paypal")
async def post_paypal_webhook(request: Request):
    raw = await request.body()
    try:
        client = _paypal()
    except HTTPException as exc:
        raise exc
    try:
        return await verify_and_process(raw_body=raw, headers=request.headers, client=client)
    except WebhookDuplicate as exc:
        return {"accepted": True, "duplicate": True, "transmission_id": exc.transmission_id}
    except WebhookRejected as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
