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

from app.escales.captain import SIMULATED_PRICE_LABEL
from app.escales.captain import chat as captain_chat
from app.escales.captain import review as captain_review
from app.escales.captain import simulated_prices, simulated_unit
from app.escales.config import (
    bryntum_scheduler_enabled,
    channel3_enabled,
    clock_start,
    simulated_now,
    elastic_evidence_enabled,
    escales_enabled,
    kernel_evidence_enabled,
    load_config,
    naviguide_bridge_enabled,
    paypal_webhook_url,
    vault_enabled,
    webhooks_enabled,
)
from app.escales.ledger import (
    _unplaced_bucket,
    fund_for_milestone,
    get_ledger,
    list_webhook_outcomes,
    record_spending,
    to_public_fund,
)
from app.escales_names import display_name as escale_display_name
from app.escales.milestones import list_milestones, record_evidence
from app.escales.naviguide_bridge import (
    clock_legs,
    escales_to_milestones,
    fetch_naviguide_export,
    legs_to_milestones,
    sync_leg_shells,
    sync_milestone_shells,
)
from app.escales.paypal_client import PayPalClient, PayPalError, approve_link
from app.escales.rate_limit import (
    RateLimited,
    client_ip,
    hit as hit_captain_rate,
    lang_for,
    limit_message,
)
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
    milestone_id: str = Field(
        "",
        description=(
            "Where the pledge sits on the route: a stop id (dep-… or ret-…) or a "
            "cabin leg id (leg-…). Empty for project_pledge and common_fund when "
            "no stopover is named. target_id is what the money is for and can "
            "differ: the bare stop slug, the same leg id, or the default projet "
            "or fonds-commun."
        ),
    )
    contributor: Optional[str] = None
    kind: Optional[str] = None
    target_id: Optional[str] = Field(
        None,
        description=(
            "What the money is for. A stopover kind stores the bare slug of "
            "milestone_id. A cabin stores the leg id, the same value as "
            "milestone_id. project_pledge defaults to projet and common_fund to "
            "fonds-commun when milestone_id is empty."
        ),
    )
    return_url: Optional[str] = None
    cancel_url: Optional[str] = None


class EvidenceIn(BaseModel):
    met: Optional[bool] = None
    facts: dict = Field(default_factory=dict)


class ChatIn(BaseModel):
    message: str


class SpendingIn(BaseModel):
    amount_eur: str
    description: str


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


def _valid_admin_key(request: Request) -> bool:
    """True when the treasurer key matches. No key stays public. A wrong key is 403."""
    provided = request.headers.get("x-admin-key", "")
    if not provided:
        return False
    _require_treasurer(request)
    return True


def _capture_conflict(exc: Exception) -> bool:
    """DECLINED, FAILED, or an expired authorization is a conflict, not a 500."""
    text = str(exc).upper()
    return any(token in text for token in ("DECLINED", "FAILED", "EXPIRED"))


def _money_http(exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError) and _capture_conflict(exc):
        return HTTPException(status_code=409, detail=str(exc))
    return _as_http(exc)


def _as_http(exc: Exception) -> HTTPException:
    if isinstance(exc, PledgeNotFound):
        return HTTPException(status_code=404, detail="Pledge not found")
    if isinstance(exc, IllegalTransition):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, PayPalError):
        # 48b7f5a mapped every PayPal error to 502, including ORDER_NOT_APPROVED.
        if "ORDER_NOT_APPROVED" in str(getattr(exc, "body", "") or ""):
            return HTTPException(status_code=409, detail="order not approved")
        return HTTPException(status_code=502, detail="PayPal request failed")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    raise exc


def _public_milestone(doc: dict) -> dict:
    milestone_id = str(doc.get("_id") or "")
    meta = doc.get("meta") or {}
    shown = meta.get("display_name") or escale_display_name(milestone_id)
    proposal = doc.get("proposal")
    if isinstance(proposal, dict):
        proposal = {
            key: value
            for key, value in proposal.items()
            if key not in {"pending_authorizations", "pledge_ids"}
        }
    return {
        "id": doc.get("_id"),
        "display_name": shown,
        "evidence": doc.get("evidence") or [],
        "proposal": proposal,
        "meta": doc.get("meta"),
        "updated_at": doc.get("updated_at"),
    }


def _public_pledge(doc: dict) -> dict:
    """Same shape as ``to_public``, plus the simulated catalogue line.

    ``approve_link`` is the buyer step. A stored order without one still
    gets the sandbox checkout URL.
    """
    public = to_public(doc)
    public["payment_mode"] = doc.get("payment_mode") or doc.get("intent")
    public["simulated_price"] = simulated_unit(str(public.get("kind") or "mile"))
    public["price_label"] = SIMULATED_PRICE_LABEL
    if not public.get("approve_link") and public.get("order_id"):
        public["approve_link"] = approve_link({"id": public["order_id"]})
    return public


async def _fund_aggregate(milestone_id: str) -> Optional[dict]:
    """Same public totals as GET /milestones/{id}/fund. No pledge list."""
    try:
        return to_public_fund(await fund_for_milestone(milestone_id))
    except LookupError:
        return None


async def _public_pledge_with_fund(doc: dict) -> dict:
    """Pledge the buyer needs, with the public fund aggregate and no pledge list."""
    public = _public_pledge(doc)
    public["fund"] = await _fund_aggregate(str(doc.get("milestone_id") or ""))
    return public


def _public_pledge_summary(doc: dict, fund: Optional[dict]) -> dict:
    """Status, amount, and the fund aggregate. Nothing that lists pledges."""
    row = doc
    return {
        "status": row.get("status"),
        "amount_eur": row.get("amount_eur"),
        "fund": fund,
    }


@router.get("/features")
async def get_features():
    cfg = load_config()
    return {
        "naviguide_bridge": naviguide_bridge_enabled(),
        "elastic": elastic_evidence_enabled(),
        "kernel": kernel_evidence_enabled(),
        "channel3": channel3_enabled(),
        "bryntum": bryntum_scheduler_enabled(),
        "vault": vault_enabled(),
        "webhooks_enabled": webhooks_enabled(),
        "webhook_url": paypal_webhook_url(),
        "paypal_client_id": cfg.client_id if cfg.configured else "",
    }


@router.get("/prices")
async def get_prices():
    return simulated_prices()


def _clock_body() -> dict:
    return {
        "start": clock_start(),
        "now": simulated_now().replace(microsecond=0).isoformat(),
    }


@router.get("/clock")
async def get_clock():
    """Public voyage clock. It does not capture or void."""
    return _clock_body()


@router.post("/clock/settle")
async def post_clock_settle(request: Request):
    """Settle departure pledges. Treasurer key. Uses the simulated clock."""
    from app.escales.departure_clock import run_departure_clock

    _require_treasurer(request)
    body = _clock_body()
    body["settled"] = await run_departure_clock(_paypal())
    return body


@router.get("/schedule")
async def get_schedule():
    export = await fetch_naviguide_export()
    await sync_milestone_shells(export)
    legs = clock_legs()
    return {
        "export": export,
        "milestones": [*escales_to_milestones(export), *legs_to_milestones(legs)],
        "legs": legs,
        "source": "naviguide" if naviguide_bridge_enabled() else "local",
        "clock": {"start": clock_start()},
        "prices": simulated_prices(),
    }


@router.post("/schedule/sync")
async def post_schedule_sync():
    docs = await sync_milestone_shells()
    docs.extend(await sync_leg_shells())
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
            kind=body.kind,
            target_id=body.target_id,
            return_url=body.return_url,
            cancel_url=body.cancel_url,
            caller_origin=f"{request.url.scheme}://{request.url.netloc}",
        )
    except (PayPalError, ValueError) as exc:
        raise _as_http(exc) from exc
    return await _public_pledge_with_fund(doc)


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
    return await _public_pledge_with_fund(doc)


@router.post("/pledges/{pledge_id}/authorize")
async def post_authorize(pledge_id: str):
    try:
        doc = await authorize_pledge(pledge_id, _paypal())
    except (PledgeNotFound, IllegalTransition, PayPalError, ValueError) as exc:
        raise _money_http(exc) from exc
    return await _public_pledge_with_fund(doc)


@router.post("/pledges/{pledge_id}/capture")
async def post_capture(pledge_id: str, request: Request):
    _require_treasurer(request)
    try:
        doc = await capture_pledge(pledge_id, _paypal())
    except (PledgeNotFound, IllegalTransition, PayPalError, ValueError) as exc:
        raise _money_http(exc) from exc
    return await _public_pledge_with_fund(doc)


@router.post("/pledges/{pledge_id}/void")
async def post_void(pledge_id: str, request: Request):
    _require_treasurer(request)
    try:
        doc = await void_pledge(pledge_id, _paypal())
    except (PledgeNotFound, IllegalTransition, PayPalError, ValueError) as exc:
        raise _money_http(exc) from exc
    return await _public_pledge_with_fund(doc)


@router.get("/pledges")
async def get_pledges(request: Request):
    """Every pledge on the server. The treasurer key is required."""
    _require_treasurer(request)
    docs = await get_ledger().list_pledges()
    return [_public_pledge(doc) for doc in docs]


@router.get("/pledges/{pledge_id}")
async def get_pledge(pledge_id: str, request: Request):
    """Public read is status, amount, and the fund aggregate. The key sees the pledge."""
    try:
        doc = await require_pledge(pledge_id)
    except PledgeNotFound as exc:
        raise _as_http(exc) from exc
    fund = await _fund_aggregate(str(doc.get("milestone_id") or ""))
    if not _valid_admin_key(request):
        return _public_pledge_summary(doc, fund)
    full = await _public_pledge_with_fund(doc)
    full["fund"] = fund
    return full


@router.get("/milestones/{milestone_id}/fund")
async def get_fund(milestone_id: str, request: Request):
    """A stopover or cabin-leg fund is public totals. Project and common fund need the key.

    The body is aggregated money only: no journal lines and no pledge ids.
    """
    if _unplaced_bucket(milestone_id):
        _require_treasurer(request)
    try:
        return to_public_fund(await fund_for_milestone(milestone_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Milestone not found") from exc


@router.post("/milestones/{milestone_id}/fund/spending")
async def post_spending(milestone_id: str, body: SpendingIn, request: Request):
    _require_treasurer(request)
    try:
        entry = await record_spending(milestone_id, body.amount_eur, body.description)
        fund = to_public_fund(await fund_for_milestone(milestone_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Milestone not found") from exc
    except ValueError as exc:
        raise _as_http(exc) from exc
    fund["entry_id"] = entry.get("id") or entry.get("_id")
    return fund


@router.get("/milestones")
async def get_milestones():
    docs = await list_milestones()
    if not docs:
        docs = await sync_milestone_shells()
    return [_public_milestone(doc) for doc in docs]


@router.post("/milestones/{milestone_id}/evidence")
async def post_evidence(milestone_id: str, body: EvidenceIn, request: Request):
    _require_treasurer(request)
    try:
        evidence = await record_evidence(milestone_id, body.met, body.facts)
    except ValueError as exc:
        raise _as_http(exc) from exc
    return {"milestone_id": milestone_id, **evidence}


def _enforce_captain_rate(request: Request, text: str = "") -> None:
    forwarded = request.headers.get("x-forwarded-for", "")
    host = request.client.host if request.client else ""
    try:
        hit_captain_rate(client_ip(forwarded, host))
    except RateLimited as exc:
        lang = lang_for(request.headers.get("accept-language", ""), text)
        raise HTTPException(
            status_code=429,
            detail=limit_message(exc.kind, lang, exc.limit),
        ) from exc


@router.post("/captain/review/{milestone_id}")
async def post_review(milestone_id: str, request: Request):
    _enforce_captain_rate(request)
    lang = lang_for(request.headers.get("accept-language", ""))
    try:
        proposal = await captain_review(milestone_id, reader=_reader(), lang=lang)
    except (PayPalError, ValueError) as exc:
        raise _as_http(exc) from exc
    if not _valid_admin_key(request):
        proposal = {
            key: value
            for key, value in proposal.items()
            if key not in {"pending_authorizations", "pledge_ids"}
        }
    return proposal


@router.post("/captain/chat")
async def post_chat(body: ChatIn, request: Request):
    _enforce_captain_rate(request, body.message)
    try:
        return await captain_chat(body.message, treasurer=_valid_admin_key(request))
    except ValueError as exc:
        raise _as_http(exc) from exc


@webhooks_router.get("/webhooks/recent")
async def get_recent_webhooks(request: Request):
    """Read-only list of webhook attempts. Treasurer key, same check as capture."""
    _require_treasurer(request)
    return {"events": await list_webhook_outcomes()}


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
