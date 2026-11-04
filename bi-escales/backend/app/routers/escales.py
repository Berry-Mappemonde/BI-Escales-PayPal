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
    clock_now_pinned,
    parse_clock_moment,
    simulated_now,
    elastic_evidence_enabled,
    escales_enabled,
    subscription_cancel_url,
    subscription_return_url,
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
    list_finance_entries,
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
from app.escales.paypal_client import PayPalClient, PayPalError, approve_link, paypal_public_error_detail
from app.escales.paypal_disputes import (
    accept_dispute_claim,
    get_dispute,
    list_dispute_snapshots,
    list_disputes as list_paypal_disputes,
    provide_dispute_evidence,
)
from app.escales.paypal_invoicing import (
    cancel_invoice,
    delete_draft_invoice,
    create_partner_invoice,
    list_treasurer_invoices,
    remind_invoice,
    send_invoice,
)
from app.escales.paypal_p2_eligibility import PAY_LATER_UI_MIN_EUR, p2_eligibility_report
from app.escales.paypal_reconcile import reconcile_paypal_ledger
from app.escales.paypal_subscriptions import (
    approve_crew_subscription,
    create_crew_subscription,
    ensure_crew_supporter_catalog,
    list_subscriptions_local,
    public_crew_supporter_plan_id,
    record_subscription,
)
from app.escales.project_payouts import (
    PayoutNotFound,
    PayoutStateError,
    approve_project_payout,
    propose_project_payout,
)
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
    refund_pledge,
    to_public,
    void_pledge,
    _http_url,
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
    lang: Optional[str] = None


class EvidenceIn(BaseModel):
    met: Optional[bool] = None
    facts: dict = Field(default_factory=dict)


class ChatIn(BaseModel):
    message: str
    lang: Optional[str] = None


class SpendingIn(BaseModel):
    amount_eur: str
    description: str


class RefundIn(BaseModel):
    amount_eur: Optional[str] = None
    now: Optional[str] = None


class CaptureIn(BaseModel):
    now: Optional[str] = None


class PayoutProposeIn(BaseModel):
    amount_eur: str
    receiver_email: str
    note: str = ""


class VaultRegisterIn(BaseModel):
    setup_token_id: Optional[str] = None


class ClockSettleIn(BaseModel):
    now: Optional[str] = None


class InvoiceCreateIn(BaseModel):
    recipient_email: str
    amount_eur: str
    description: str
    reference: str = ""
    invoice_number: Optional[str] = None


class DisputeEvidenceIn(BaseModel):
    milestone_id: str
    notes: Optional[str] = None


class DisputeAcceptIn(BaseModel):
    note: str = ""


class SubscriptionRecordIn(BaseModel):
    subscription_id: str
    plan_id: str
    status: str = "ACTIVE"
    subscriber_email: Optional[str] = None


class SubscriptionCreateIn(BaseModel):
    return_url: Optional[str] = None
    cancel_url: Optional[str] = None


class SubscriptionApproveIn(BaseModel):
    subscription_id: str
    plan_id: str


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


def _treasurer_reader(request: Request) -> Optional[ReadOnlyTools]:
    if not _valid_admin_key(request):
        return None
    return _reader()


def _capture_conflict(exc: Exception) -> bool:
    """DECLINED, FAILED, or an expired authorization is a conflict, not a 500."""
    text = str(exc).upper()
    return any(token in text for token in ("DECLINED", "FAILED", "EXPIRED"))


def _paypal_error_blob(exc: PayPalError) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        import json

        return json.dumps(body)
    return str(body or "")


def _paypal_order_not_approved(exc: PayPalError) -> bool:
    blob = _paypal_error_blob(exc).upper()
    if "ORDER_NOT_APPROVED" in blob:
        return True
    if exc.status in {400, 422} and "UNPROCESSABLE_ENTITY" in blob:
        return "ORDER" in blob and "APPROV" in blob
    return False


def _paypal_client_error_detail(exc: PayPalError) -> str:
    public = paypal_public_error_detail(exc.body)
    if public:
        return public
    body = exc.body
    if isinstance(body, dict):
        details = body.get("details")
        if isinstance(details, list):
            parts: list[str] = []
            for item in details:
                if not isinstance(item, dict):
                    continue
                issue = item.get("issue") or item.get("description")
                if issue:
                    parts.append(str(issue))
            if parts:
                return "; ".join(parts)
        for key in ("message", "error_description", "name"):
            value = body.get(key)
            if value:
                return str(value)
    if exc.status == 404:
        return "PayPal transaction search returned no data for this date window"
    return "PayPal request rejected"


def _money_http(exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError):
        if str(exc) == "order not approved yet":
            return HTTPException(status_code=409, detail=str(exc))
        if _capture_conflict(exc):
            return HTTPException(status_code=409, detail=str(exc))
    return _as_http(exc)


def _as_http(exc: Exception) -> HTTPException:
    if isinstance(exc, PledgeNotFound):
        return HTTPException(status_code=404, detail="Pledge not found")
    if isinstance(exc, IllegalTransition):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, PayPalError):
        if _paypal_order_not_approved(exc):
            return HTTPException(status_code=409, detail="order not approved yet")
        if 400 <= exc.status < 500:
            return HTTPException(
                status_code=exc.status,
                detail=_paypal_client_error_detail(exc),
            )
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
    crew_plan_id = await public_crew_supporter_plan_id()
    return {
        "naviguide_bridge": naviguide_bridge_enabled(),
        "elastic": elastic_evidence_enabled(),
        "kernel": kernel_evidence_enabled(),
        "channel3": channel3_enabled(),
        "bryntum": bryntum_scheduler_enabled(),
        "vault": vault_enabled(),
        "webhooks_enabled": webhooks_enabled(),
        "webhook_url": paypal_webhook_url(),
        "clock_pinned": clock_now_pinned(),
        "pay_later_min_eur": PAY_LATER_UI_MIN_EUR,
        "p2_eligibility": p2_eligibility_report(),
        "crew_supporter_plan_id": crew_plan_id,
        "fastlane": False,
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
async def post_clock_settle(request: Request, payload: ClockSettleIn = ClockSettleIn()):
    """Settle departure pledges. Treasurer key. Uses the simulated clock."""
    from app.escales.departure_clock import run_departure_clock

    _require_treasurer(request)
    settle_at = None
    if payload.now is not None and str(payload.now).strip():
        if not clock_now_pinned():
            raise HTTPException(
                status_code=400,
                detail="clock settle override requires ESCALES_CLOCK_NOW",
            )
        settle_at = parse_clock_moment(str(payload.now))
    body = _clock_body()
    if settle_at is not None:
        body["now"] = settle_at.replace(microsecond=0).isoformat()
    body["settled"] = await run_departure_clock(_paypal(), now=settle_at)
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
        doc = await create_pledge(
            amount_eur=body.amount_eur,
            description=body.description,
            milestone_id=body.milestone_id,
            contributor=body.contributor,
            client=_paypal(),
            client_key=client_key,
            kind=body.kind,
            target_id=body.target_id,
            return_url=body.return_url,
            cancel_url=body.cancel_url,
            caller_origin=f"{request.url.scheme}://{request.url.netloc}",
            checkout_locale=body.lang or lang_for(request.headers.get("accept-language", "")),
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
async def post_capture(pledge_id: str, request: Request, body: CaptureIn = CaptureIn()):
    _require_treasurer(request)
    effective_at = None
    if (body.now or "").strip():
        if not clock_now_pinned():
            raise HTTPException(
                status_code=422,
                detail="capture timestamp override requires ESCALES_CLOCK_NOW",
            )
        effective_at = parse_clock_moment(str(body.now))
    try:
        doc = await capture_pledge(pledge_id, _paypal(), effective_at=effective_at)
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


@router.post("/pledges/{pledge_id}/refund")
async def post_refund(pledge_id: str, body: RefundIn, request: Request):
    _require_treasurer(request)
    effective_at = None
    if (body.now or "").strip():
        if not clock_now_pinned():
            raise HTTPException(
                status_code=422,
                detail="refund timestamp override requires ESCALES_CLOCK_NOW",
            )
        effective_at = parse_clock_moment(str(body.now))
    try:
        doc = await refund_pledge(
            pledge_id,
            _paypal(),
            amount_eur=body.amount_eur,
            effective_at=effective_at,
        )
    except (PledgeNotFound, IllegalTransition, PayPalError, ValueError) as exc:
        raise _money_http(exc) from exc
    return await _public_pledge_with_fund(doc)


@router.get("/paypal/reconcile")
async def get_paypal_reconcile(request: Request, start_date: str, end_date: str):
    """Read-only ledger vs PayPal Transaction Search. Treasurer key required."""
    _require_treasurer(request)
    try:
        return await reconcile_paypal_ledger(
            start_date=start_date,
            end_date=end_date,
            client=_paypal(),
            finance_entries=await list_finance_entries(),
        )
    except PayPalError as exc:
        raise _as_http(exc) from exc


@router.get("/paypal/disputes")
async def get_paypal_disputes(request: Request, start_time: Optional[str] = None):
    _require_treasurer(request)
    try:
        remote = await list_paypal_disputes(_paypal(), start_time=start_time)
        return {"paypal": remote, "snapshots": await list_dispute_snapshots()}
    except PayPalError as exc:
        raise _as_http(exc) from exc


@router.get("/paypal/disputes/{dispute_id}")
async def get_paypal_dispute(dispute_id: str, request: Request):
    _require_treasurer(request)
    try:
        return await get_dispute(_paypal(), dispute_id)
    except PayPalError as exc:
        raise _as_http(exc) from exc


@router.post("/paypal/disputes/{dispute_id}/accept-claim")
async def post_dispute_accept(dispute_id: str, body: DisputeAcceptIn, request: Request):
    _require_treasurer(request)
    try:
        return await accept_dispute_claim(_paypal(), dispute_id, note=body.note)
    except PayPalError as exc:
        raise _as_http(exc) from exc


@router.post("/paypal/disputes/{dispute_id}/provide-evidence")
async def post_dispute_evidence(dispute_id: str, body: DisputeEvidenceIn, request: Request):
    _require_treasurer(request)
    try:
        return await provide_dispute_evidence(
            _paypal(),
            dispute_id,
            milestone_id=body.milestone_id,
            notes=body.notes,
        )
    except PayPalError as exc:
        raise _as_http(exc) from exc


@router.get("/paypal/invoices")
async def get_paypal_invoices(request: Request, page: int = 1):
    _require_treasurer(request)
    try:
        return await list_treasurer_invoices(_paypal(), page=page)
    except PayPalError as exc:
        raise _as_http(exc) from exc


@router.post("/paypal/invoices")
async def post_paypal_invoice(body: InvoiceCreateIn, request: Request):
    _require_treasurer(request)
    try:
        return await create_partner_invoice(
            _paypal(),
            recipient_email=body.recipient_email,
            amount_eur=body.amount_eur,
            description=body.description,
            reference=body.reference or body.description,
            invoice_number=body.invoice_number,
        )
    except PayPalError as exc:
        raise _as_http(exc) from exc


@router.post("/paypal/invoices/{invoice_id}/send")
async def post_invoice_send(invoice_id: str, request: Request):
    _require_treasurer(request)
    try:
        return await send_invoice(_paypal(), invoice_id)
    except PayPalError as exc:
        raise _as_http(exc) from exc


@router.post("/paypal/invoices/{invoice_id}/remind")
async def post_invoice_remind(invoice_id: str, request: Request):
    _require_treasurer(request)
    try:
        return await remind_invoice(_paypal(), invoice_id)
    except PayPalError as exc:
        raise _as_http(exc) from exc


@router.post("/paypal/invoices/{invoice_id}/cancel")
async def post_invoice_cancel(invoice_id: str, request: Request):
    _require_treasurer(request)
    try:
        return await cancel_invoice(_paypal(), invoice_id)
    except PayPalError as exc:
        raise _as_http(exc) from exc


@router.delete("/paypal/invoices/{invoice_id}")
async def delete_invoice_route(invoice_id: str, request: Request):
    """Remove a draft invoice (PayPal only cancels sent invoices)."""
    _require_treasurer(request)
    try:
        return await delete_draft_invoice(_paypal(), invoice_id)
    except PayPalError as exc:
        raise _as_http(exc) from exc


@router.post("/paypal/subscriptions/setup")
async def post_subscription_setup(request: Request):
    """Idempotent Crew supporter product + monthly EUR plan (admin)."""
    _require_treasurer(request)
    try:
        return await ensure_crew_supporter_catalog(_paypal())
    except PayPalError as exc:
        raise _as_http(exc) from exc


@router.get("/paypal/subscriptions/plan")
async def get_crew_subscription_plan():
    """Public read-only Crew supporter billing plan id (does not create a PayPal subscription)."""
    plan_id = await public_crew_supporter_plan_id()
    return {"plan_id": plan_id}


@router.post("/paypal/subscriptions/create")
async def post_subscription_create(request: Request, body: SubscriptionCreateIn = SubscriptionCreateIn()):
    """Buyer checkout: catalog + PayPal subscription (public)."""
    caller = f"{request.url.scheme}://{request.url.netloc}"
    try:
        back = _http_url(
            body.return_url,
            subscription_return_url(),
            "return_url",
            caller_origin=caller,
        )
        cancel = _http_url(
            body.cancel_url,
            subscription_cancel_url(),
            "cancel_url",
            caller_origin=caller,
        )
        return await create_crew_subscription(
            _paypal(),
            return_url=back,
            cancel_url=cancel,
            client_key=request.headers.get("paypal-request-id"),
        )
    except (PayPalError, ValueError) as exc:
        raise _as_http(exc) from exc


@router.get("/paypal/subscriptions")
async def get_paypal_subscriptions(request: Request):
    _require_treasurer(request)
    return {"items": await list_subscriptions_local()}


@router.post("/paypal/subscriptions/record")
async def post_subscription_record(body: SubscriptionRecordIn, request: Request):
    _require_treasurer(request)
    try:
        return await record_subscription(
            subscription_id=body.subscription_id,
            plan_id=body.plan_id,
            status=body.status,
            subscriber_email=body.subscriber_email,
        )
    except ValueError as exc:
        raise _as_http(exc) from exc


@router.post("/paypal/subscriptions/approve")
async def post_subscription_approve(body: SubscriptionApproveIn):
    """Record buyer subscription after SDK approval (public)."""
    try:
        return await approve_crew_subscription(
            _paypal(),
            subscription_id=body.subscription_id,
            plan_id=body.plan_id,
        )
    except (PayPalError, ValueError) as exc:
        raise _as_http(exc) from exc


@router.post("/projects/{project_id}/payouts")
async def post_project_payout(project_id: str, body: PayoutProposeIn, request: Request):
    """Propose a project payout. PayPal is not called until approve."""
    _require_treasurer(request)
    try:
        return await propose_project_payout(
            project_id,
            amount_eur=body.amount_eur,
            receiver_email=body.receiver_email,
            note=body.note,
        )
    except ValueError as exc:
        raise _as_http(exc) from exc


@router.post("/payouts/{payout_id}/approve")
async def post_payout_approve(payout_id: str, request: Request):
    """Second human step: send a proposed payout to PayPal sandbox."""
    _require_treasurer(request)
    try:
        return await approve_project_payout(payout_id, _paypal())
    except PayoutNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PayoutStateError as exc:
        msg = str(exc).lower()
        if "already" in msg or "failed" in msg:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise _as_http(exc) from exc
    except (PayPalError, ValueError) as exc:
        raise _as_http(exc) from exc


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
        return await captain_chat(
            body.message,
            treasurer=_valid_admin_key(request),
            lang=body.lang,
            accept_language=request.headers.get("accept-language", ""),
            reader=_treasurer_reader(request),
        )
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
