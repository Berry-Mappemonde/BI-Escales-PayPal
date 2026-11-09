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

from app.core import llm
from app.gear_projects_catalog import (
    funded_percent,
    get_gear_feature_collection,
    is_fully_funded_amount,
    lookup_project_fund_meta,
    sanitize_public_gear_collection,
)
from app.escales.captain import chat as captain_chat
from app.escales.captain import review as captain_review
from app.escales.captain import simulated_price_label, simulated_prices, simulated_unit
from app.escales.config import (
    bryntum_scheduler_enabled,
    card_fields_enabled,
    channel3_enabled,
    wishlists_enabled,
    clock_start,
    clock_now_pinned,
    parse_clock_moment,
    simulated_now,
    demo_treasurer_enabled,
    demo_treasurer_env_forbidden,
    elastic_evidence_enabled,
    escales_enabled,
    escales_env,
    subscription_cancel_url,
    subscription_return_url,
    kernel_evidence_enabled,
    load_config,
    naviguide_bridge_enabled,
    paypal_webhook_url,
    vault_enabled,
    vault_on_purchase_enabled,
    wallet_pay_enabled,
    webhooks_enabled,
)
from app.escales.ledger import (
    _project_fund_target,
    _unplaced_bucket,
    fund_for_milestone,
    fund_milestone_for_pledge,
    get_ledger,
    list_finance_entries,
    list_webhook_outcomes,
    record_spending,
    to_public_fund,
    to_public_project_donation_total,
)
from app.escales_names import display_name as escale_display_name
from app.escales.milestones import (
    captain_review_approved,
    list_milestones,
    record_captain_review_approval,
    record_evidence,
)
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
    resolve_crew_supporter_plan_id,
)
from app.escales.project_payouts import (
    PayoutNotFound,
    PayoutStateError,
    approve_project_payout,
    propose_project_payout,
)
from app.escales.app_i18n import (
    error_payload,
    resolve_app_language,
    validation_code_from_message,
)
from app.escales.rate_limit import (
    RateLimited,
    captain_rate_feature,
    captain_rate_key,
    client_ip,
    hit as hit_captain_rate,
    limit_message,
)
from app.escales.certificates import (
    ensure_certificate,
    load_certificate,
    payer_proof_matches,
    public_certificate_links,
    render_certificate_pdf,
    render_certificate_png,
)
from app.escales.pledges import (
    IllegalTransition,
    PledgeAlreadyFullyRefunded,
    PledgeNotFound,
    RefundRequestKeyRequired,
    admin_reauthorize_pledge,
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


class CertificateIn(BaseModel):
    payer_proof: Optional[str] = Field(
        None,
        description="PayPal order id or vault setup token id from the buyer checkout response.",
    )
    display_name: Optional[str] = Field(None, max_length=120)


class PledgeIn(BaseModel):
    quantity: Optional[int] = Field(None, ge=1, le=1000, strict=True)
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
    checkout_method: Optional[str] = Field(
        None,
        description="wallet (default) or card when ESCALES_CARD_FIELDS_ENABLED is on.",
    )


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
    request_key: Optional[str] = Field(
        None,
        description=(
            "Per-refund idempotency token; maps to PayPal-Request-Id "
            "(refund-{pledge_id}-{request_key}). Replays return HTTP 200 with the existing pledge."
        ),
    )
    paypal_refund_id: Optional[str] = Field(
        None,
        description=(
            "PayPal refund resource id when reconciling a webhook-first refund. "
            "On idempotent replay the public pledge includes refund_id; HTTP 409 responses "
            "include paypal_refund_id when the pledge is already fully refunded."
        ),
    )


class CaptureIn(BaseModel):
    now: Optional[str] = None


class ReauthorizeIn(BaseModel):
    mock_response: Optional[str] = Field(
        None,
        description="Optional PayPal-Mock-Response JSON for sandbox negative testing.",
    )
    now: Optional[str] = Field(
        None,
        description="Optional simulated-clock moment (requires ESCALES_CLOCK_NOW).",
    )


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
    lang: Optional[str] = None


class DisputeEvidenceIn(BaseModel):
    milestone_id: str
    notes: Optional[str] = None
    lang: Optional[str] = None


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
    lang: Optional[str] = None


class SubscriptionApproveIn(BaseModel):
    subscription_id: str
    plan_id: str


def _paypal(lang: Optional[str] = None) -> Any:
    if _client_factory is not None:
        return _client_factory()
    cfg = load_config()
    if not cfg.configured:
        if lang is not None:
            raise HTTPException(
                status_code=503,
                detail=error_payload("paypal_not_configured", lang),
            )
        raise HTTPException(status_code=503, detail="PayPal sandbox is not configured")
    return PayPalClient(cfg)


def _reader() -> Optional[ReadOnlyTools]:
    try:
        client = _paypal()
    except HTTPException:
        return None
    return ReadOnlyTools(client)


def _has_admin_key_header(request: Request) -> bool:
    return bool(request.headers.get("x-admin-key", "").strip())


def _demo_treasurer_session(request: Request) -> bool:
    return demo_treasurer_enabled() and not _has_admin_key_header(request)


def _demo_forbidden_http() -> HTTPException:
    return HTTPException(
        status_code=403,
        detail="Demo treasurer requires PAYPAL_ENV=sandbox and ESCALES_ENV other than production",
    )


def _require_treasurer_or_demo(request: Request) -> bool:
    """Key holder -> True. Read-only demo session (sandbox, non-production) -> False.

    Only read routes may call this. Money routes (capture, void, approve) use
    ``_require_treasurer`` so demo mode can never move funds.
    """
    if _has_admin_key_header(request):
        _require_treasurer(request)
        return True
    if demo_treasurer_env_forbidden():
        raise _demo_forbidden_http()
    if _demo_treasurer_session(request):
        return False
    _require_treasurer(request)
    return True


def _treasurer_privileged(request: Request) -> bool:
    """Full pledge detail only with a valid treasurer key; demo sessions stay redacted."""
    if _has_admin_key_header(request):
        _require_treasurer(request)
        return True
    if demo_treasurer_env_forbidden():
        raise _demo_forbidden_http()
    return False


# Fields a keyless demo session may see in GET /pledges: no contributor, payer, or order ids.
_DEMO_PLEDGE_FIELDS = (
    "id",
    "status",
    "amount_eur",
    "currency",
    "kind",
    "milestone_id",
    "target_id",
    "payment_mode",
    "intent",
    "simulated_price",
    "price_label",
    "created_at",
    "updated_at",
)


def _demo_pledge_row(public: dict) -> dict:
    return {key: public[key] for key in _DEMO_PLEDGE_FIELDS if key in public}


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


def _money_http(exc: Exception, lang: Optional[str] = None) -> HTTPException:
    if isinstance(exc, RefundRequestKeyRequired):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ValueError):
        if str(exc) == "order not approved yet":
            if lang is not None:
                return HTTPException(
                    status_code=409,
                    detail=error_payload("order_not_approved", lang),
                )
            return HTTPException(status_code=409, detail=str(exc))
        if _capture_conflict(exc):
            return HTTPException(status_code=409, detail=str(exc))
    return _as_http(exc, lang=lang)


def _as_http(exc: Exception, lang: Optional[str] = None) -> HTTPException:
    localized = lang is not None
    app_lang = resolve_app_language(lang) if localized else None

    if isinstance(exc, PledgeNotFound):
        if localized:
            return HTTPException(
                status_code=404,
                detail=error_payload("pledge_not_found", app_lang),
            )
        return HTTPException(status_code=404, detail="Pledge not found")
    if isinstance(exc, IllegalTransition):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, PayPalError):
        if _paypal_order_not_approved(exc):
            if localized:
                return HTTPException(
                    status_code=409,
                    detail=error_payload("order_not_approved", app_lang),
                )
            return HTTPException(status_code=409, detail="order not approved yet")
        if 400 <= exc.status < 500:
            return HTTPException(
                status_code=exc.status,
                detail=_paypal_client_error_detail(exc),
            )
        if localized:
            return HTTPException(
                status_code=502,
                detail=error_payload("paypal_request_failed", app_lang),
            )
        return HTTPException(status_code=502, detail="PayPal request failed")
    if isinstance(exc, ValueError):
        msg = str(exc)
        if localized:
            code = validation_code_from_message(msg)
            if code:
                return HTTPException(
                    status_code=422,
                    detail=error_payload(code, app_lang),
                )
            return HTTPException(
                status_code=422,
                detail={"code": "validation_error", "detail": msg},
            )
        return HTTPException(status_code=422, detail=msg)
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


def _public_pledge(doc: dict, *, lang: Optional[str] = None) -> dict:
    """Same shape as ``to_public``, plus the simulated catalogue line.

    ``approve_link`` is the buyer step. A stored order without one still
    gets the sandbox checkout URL.
    """
    resolved = resolve_app_language(lang)
    public = to_public(doc)
    public["payment_mode"] = doc.get("payment_mode") or doc.get("intent")
    kind = str(public.get("kind") or "mile")
    public["simulated_price"] = simulated_unit(kind, resolved)
    pledge_ccy = str(doc.get("currency") or "EUR").strip().upper()
    if pledge_ccy != "EUR":
        public["simulated_price"]["currency"] = pledge_ccy
    public["price_label"] = simulated_price_label(resolved)
    if not public.get("approve_link") and public.get("order_id"):
        public["approve_link"] = approve_link({"id": public["order_id"]})
    return public


async def _fund_aggregate(milestone_id: str) -> Optional[dict]:
    """Same public totals as GET /milestones/{id}/fund. No pledge list."""
    try:
        return to_public_fund(await fund_for_milestone(milestone_id))
    except LookupError:
        return None


async def _public_pledge_with_fund(doc: dict, *, lang: Optional[str] = None) -> dict:
    """Pledge the buyer needs, with the public fund aggregate and no pledge list."""
    public = _public_pledge(doc, lang=lang)
    public["fund"] = await _fund_aggregate(fund_milestone_for_pledge(doc))
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
        "wishlists": wishlists_enabled(),
        "bryntum": bryntum_scheduler_enabled(),
        "vault": vault_enabled(),
        "card_fields": card_fields_enabled(),
        "vault_on_purchase": vault_on_purchase_enabled(),
        "wallet_pay": wallet_pay_enabled(),
        "webhooks_enabled": webhooks_enabled(),
        "webhook_url": paypal_webhook_url(),
        "clock_pinned": clock_now_pinned(),
        "pay_later_min_eur": PAY_LATER_UI_MIN_EUR,
        "p2_eligibility": p2_eligibility_report(),
        "crew_supporter_plan_id": crew_plan_id,
        "demo_treasurer": demo_treasurer_enabled(),
        "fastlane": False,
        "captain_rate": captain_rate_feature(),
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
    from ..escales.navigation_logbook import navigation_logbook

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
        "logbook": navigation_logbook(export),
    }


@router.post("/schedule/sync")
async def post_schedule_sync():
    docs = await sync_milestone_shells()
    docs.extend(await sync_leg_shells())
    return [_public_milestone(doc) for doc in docs]


@router.get("/pledges/mode")
async def get_pledge_mode(milestone_id: str, kind: str = "mile"):
    """Read-only card checkout preview: no PayPal calls or ledger writes."""
    from app.escales.payment_mode import preview_payment_mode
    try:
        mode = await preview_payment_mode(milestone_id, kind)
        return {"payment_mode": mode}
    except ValueError as exc:
        raise _as_http(exc) from exc


@router.post("/pledges")
async def post_pledge(body: PledgeIn, request: Request):
    client_key = request.headers.get("paypal-request-id")
    try:
        doc = await create_pledge(
            quantity=body.quantity,
            amount_eur=body.amount_eur,
            description=body.description,
            milestone_id=body.milestone_id,
            contributor=body.contributor,
            client=_paypal(body.lang),
            client_key=client_key,
            kind=body.kind,
            target_id=body.target_id,
            return_url=body.return_url,
            cancel_url=body.cancel_url,
            caller_origin=f"{request.url.scheme}://{request.url.netloc}",
            checkout_locale=resolve_app_language(body.lang),
            checkout_method=body.checkout_method,
        )
    except (PayPalError, ValueError) as exc:
        raise _as_http(exc, lang=body.lang) from exc
    return await _public_pledge_with_fund(doc, lang=resolve_app_language(body.lang))


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
        pledge = await require_pledge(pledge_id)
        milestone_id = str(pledge.get("milestone_id") or "")
        if milestone_id and pledge.get("status") in {
            "authorized", "capture_failed", "vaulted", "charge_failed",
        }:
            from app.escales.departure_clock import refuse_early_capture

            await refuse_early_capture(pledge, now=effective_at)
            if not await captain_review_approved(milestone_id, now=effective_at):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "capture requires an approved Captain capture review at or after "
                        "stop arrival (leg departure for cabins)"
                    ),
                )
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


def _resolve_refund_request_key(request: Request, body: RefundIn) -> Optional[str]:
    """Per-refund idempotency token for ``refund_pledge`` (maps to PayPal-Request-Id).

    ``Idempotency-Key`` header wins when present; otherwise ``request_key`` in the JSON body.
    If both differ, the header value is used (not rejected).
    """
    header = (
        request.headers.get("Idempotency-Key")
        or request.headers.get("idempotency-key")
        or ""
    ).strip()
    if header:
        return header
    field = (body.request_key or "").strip()
    return field or None


@router.post(
    "/pledges/{pledge_id}/refund",
    responses={
        409: {
            "description": (
                "Conflict: illegal state, duplicate amount without request_key, "
                "or pledge already fully refunded (body includes paypal_refund_id)."
            ),
        },
    },
)
async def post_refund(pledge_id: str, body: RefundIn, request: Request):
    """Treasurer refund for a captured pledge (sandbox authorize-then-capture flow).

    Idempotent replays (same ``request_key`` / ``Idempotency-Key`` or matching
    ``paypal_refund_id``) return HTTP 200 and the public pledge; the pledge
    ``refund_id`` field is the latest PayPal refund resource id.

    When nothing remains refundable and the call is not a replay, HTTP 409 returns
    ``detail`` plus ``paypal_refund_id`` (the PayPal refund id already on file).
    """
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
            request_key=_resolve_refund_request_key(request, body),
            paypal_refund_id=(body.paypal_refund_id or "").strip() or None,
        )
    except PledgeAlreadyFullyRefunded as exc:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=409,
            content={
                "detail": "pledge already fully refunded",
                "paypal_refund_id": exc.paypal_refund_id,
            },
        )
    except (PledgeNotFound, IllegalTransition, PayPalError, ValueError, RefundRequestKeyRequired) as exc:
        raise _money_http(exc) from exc
    return await _public_pledge_with_fund(doc)


@router.post("/admin/pledges/{pledge_id}/reauthorize")
async def post_admin_reauthorize(
    pledge_id: str,
    request: Request,
    body: ReauthorizeIn = ReauthorizeIn(),
):
    """TEST-only: treasurer route to exercise honor-period reauthorize (not in production)."""
    if escales_env() == "production":
        raise HTTPException(status_code=404, detail="Not Found")
    _require_treasurer(request)
    effective_at = None
    if (body.now or "").strip():
        if not clock_now_pinned():
            raise HTTPException(
                status_code=422,
                detail="reauthorize timestamp override requires ESCALES_CLOCK_NOW",
            )
        effective_at = parse_clock_moment(str(body.now))
    try:
        doc = await admin_reauthorize_pledge(
            pledge_id,
            _paypal(),
            mock_response=(body.mock_response or "").strip() or None,
            effective_at=effective_at,
        )
    except (PledgeNotFound, PayPalError, ValueError) as exc:
        raise _money_http(exc) from exc
    return await _public_pledge_with_fund(doc)


@router.get("/paypal/reconcile")
async def get_paypal_reconcile(
    request: Request,
    start_date: str,
    end_date: str,
    lang: Optional[str] = None,
):
    """Read-only ledger vs PayPal Transaction Search. Treasurer key required."""
    _require_treasurer(request)
    app_lang = resolve_app_language(lang)
    try:
        report = await reconcile_paypal_ledger(
            start_date=start_date,
            end_date=end_date,
            client=_paypal(app_lang),
            finance_entries=await list_finance_entries(),
            lang=app_lang,
        )
        return report
    except PayPalError as exc:
        raise _as_http(exc, lang=app_lang) from exc


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
    app_lang = resolve_app_language(body.lang)
    try:
        return await provide_dispute_evidence(
            _paypal(app_lang),
            dispute_id,
            milestone_id=body.milestone_id,
            notes=body.notes,
            lang=app_lang,
        )
    except PayPalError as exc:
        raise _as_http(exc, lang=app_lang) from exc


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
    app_lang = resolve_app_language(body.lang)
    try:
        return await create_partner_invoice(
            _paypal(app_lang),
            recipient_email=body.recipient_email,
            amount_eur=body.amount_eur,
            description=body.description,
            reference=body.reference or body.description,
            invoice_number=body.invoice_number,
            lang=app_lang,
        )
    except PayPalError as exc:
        raise _as_http(exc, lang=app_lang) from exc


@router.post("/paypal/invoices/{invoice_id}/send")
async def post_invoice_send(invoice_id: str, request: Request):
    _require_treasurer(request)
    try:
        return await send_invoice(_paypal(), invoice_id)
    except PayPalError as exc:
        raise _as_http(exc) from exc


@router.post("/paypal/invoices/{invoice_id}/remind")
async def post_invoice_remind(
    invoice_id: str,
    request: Request,
    lang: Optional[str] = None,
):
    _require_treasurer(request)
    app_lang = resolve_app_language(lang)
    try:
        return await remind_invoice(_paypal(app_lang), invoice_id, lang=app_lang)
    except PayPalError as exc:
        raise _as_http(exc, lang=app_lang) from exc


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
async def get_crew_subscription_plan(lang: Optional[str] = None):
    """Public read-only Crew supporter billing plan id (hydrates from PayPal when needed)."""
    app_lang = resolve_app_language(lang)
    try:
        plan_id = await resolve_crew_supporter_plan_id(_paypal(app_lang), lang=app_lang)
    except PayPalError as exc:
        raise _as_http(exc, lang=app_lang) from exc
    return {"plan_id": plan_id, "lang": app_lang}


@router.post("/paypal/subscriptions/create")
async def post_subscription_create(request: Request, body: SubscriptionCreateIn = SubscriptionCreateIn()):
    """Buyer checkout: catalog + PayPal subscription (public)."""
    app_lang = resolve_app_language(body.lang)
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
            _paypal(app_lang),
            return_url=back,
            cancel_url=cancel,
            client_key=request.headers.get("paypal-request-id"),
            lang=app_lang,
        )
    except (PayPalError, ValueError) as exc:
        raise _as_http(exc, lang=app_lang) from exc


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


@router.get("/gear")
async def get_public_gear_list():
    """Expedition Gear projects (sandbox seed + optional Channel3 search when enabled)."""
    payload = await get_gear_feature_collection()
    return await sanitize_public_gear_collection(payload)


@router.get("/expedition/cart")
async def get_expedition_cart(lang: Optional[str] = None):
    """Expedition cart price table: six gear lines and every voyage marina (QA R3b-2)."""
    from app.expedition_cart import build_expedition_cart

    return await build_expedition_cart(lang)


@router.get("/projects/{project_id}/fund")
async def get_public_project_fund(project_id: str):
    """Public crowdfunding totals for one BI project (``target_id`` slug).

    Same spirit as public stopover ``GET /milestones/{id}/fund`` via ``to_public_fund``:
    aggregates only. Treasurer detail stays on ``GET /milestones/{project_id}/fund``.
    """
    from app.channel3_catalog import lookup_catalog_by_project_id
    from app.channel3_funding import enrich_item_funding, fund_snapshot_for_project
    from app.channel3_paypal import catalog_project_id
    from app.channel3_public import apply_buy_link_policy

    if catalog_project_id(project_id):
        catalog = lookup_catalog_by_project_id(project_id, public_only=True)
        if not catalog:
            raise HTTPException(status_code=404, detail="Project fund not found")
    else:
        catalog = lookup_catalog_by_project_id(project_id)
    meta = lookup_project_fund_meta(project_id)
    try:
        if catalog:
            fund = await fund_snapshot_for_project(project_id)
        else:
            if await _project_fund_target(project_id) is None:
                raise LookupError("not a project fund")
            fund = await fund_for_milestone(project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Project fund not found") from exc
    goal_eur = str((meta or {}).get("goal_eur") or "").strip()
    goal_amount = goal_eur or str((meta or {}).get("channel3_price") or "").strip()
    goal_currency = (
        "EUR"
        if goal_eur
        else str((meta or {}).get("channel3_currency") or (meta or {}).get("goal_currency") or "EUR").strip().upper()
    )
    if catalog:
        enriched = enrich_item_funding(catalog, fund)
        base = to_public_project_donation_total(fund)
        payload = {**base, **{k: enriched[k] for k in enriched if k not in ("channel3_buy_url", "product_url")}}
        payload["project_kind"] = "gear_project"
        if meta and meta.get("channel3_product_name"):
            payload["channel3_product_name"] = meta["channel3_product_name"]
        buy_url = (meta or {}).get("channel3_buy_url") or catalog.get("channel3_buy_url")
        return apply_buy_link_policy(
            payload,
            fully_funded=bool(enriched.get("fully_funded")),
            buy_url=buy_url,
        )
    if goal_amount:
        base = to_public_project_donation_total(fund)
        fund_currency = str(base.get("currency") or "EUR").strip().upper()
        pct = funded_percent(
            base["amount_eur"],
            goal_amount,
            amount_currency=fund_currency,
            goal_currency=goal_currency,
        )
        fully = is_fully_funded_amount(
            base["amount_eur"],
            goal_amount,
            amount_currency=fund_currency,
            goal_currency=goal_currency,
        )
        payload = to_public_project_donation_total(
            fund,
            goal_eur=goal_eur or None,
            funded_pct=pct,
        )
        meta_keys = (
            "channel3_image_url",
            "project_kind",
            "channel3_product_name",
            "channel3_price",
            "channel3_currency",
            "goal_currency",
            "price_amount_minor",
            "price_currency",
        )
        if meta:
            for key in meta_keys:
                if meta.get(key):
                    payload[key] = meta[key]
        if not goal_eur and goal_amount:
            payload["goal_amount"] = goal_amount
            payload["goal_currency"] = goal_currency
        payload["fully_funded"] = fully
        buy_url = str((meta or {}).get("channel3_buy_url") or "").strip() or None
        return apply_buy_link_policy(payload, fully_funded=fully, buy_url=buy_url)
    return to_public_project_donation_total(fund)


@router.get("/common-fund/fund")
async def get_public_common_fund():
    """Public boat common-fund totals (pattern: ``GET /projects/{id}/fund`` from N33)."""
    try:
        return to_public_fund(await fund_for_milestone("fonds-commun"))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Common fund not found") from exc


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
async def post_payout_approve(payout_id: str, request: Request, lang: Optional[str] = None):
    """Second human step: send a proposed payout to PayPal sandbox."""
    _require_treasurer(request)
    app_lang = resolve_app_language(lang)
    try:
        return await approve_project_payout(payout_id, _paypal(app_lang), lang=app_lang)
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
    """Every pledge on the server. The key sees everything; a sandbox demo session sees a
    redacted list (status and amounts, never contributor names or PayPal ids)."""
    keyed = _require_treasurer_or_demo(request)
    docs = await get_ledger().list_pledges()
    rows = [_public_pledge(doc) for doc in docs]
    return rows if keyed else [_demo_pledge_row(row) for row in rows]


@router.get("/pledges/{pledge_id}")
async def get_pledge(pledge_id: str, request: Request):
    """Public read is status, amount, and the fund aggregate. The key sees the pledge."""
    try:
        doc = await require_pledge(pledge_id)
    except PledgeNotFound as exc:
        raise _as_http(exc) from exc
    fund = await _fund_aggregate(fund_milestone_for_pledge(doc))
    if not _valid_admin_key(request):
        return _public_pledge_summary(doc, fund)
    full = await _public_pledge_with_fund(doc)
    full["fund"] = fund
    return full


@router.post("/pledges/{pledge_id}/certificate")
async def post_pledge_certificate(
    pledge_id: str,
    lang: Optional[str] = None,
    body: CertificateIn = CertificateIn(),
):
    """Issue (once) a mile sponsorship certificate after a successful mile pledge."""
    app_lang = resolve_app_language(lang)
    try:
        pledge = await require_pledge(pledge_id)
    except PledgeNotFound as exc:
        raise HTTPException(status_code=404, detail="Pledge not found") from exc
    if not payer_proof_matches(pledge, body.payer_proof):
        raise HTTPException(status_code=403, detail="Payer proof required")
    try:
        doc = await ensure_certificate(
            pledge_id,
            display_name=body.display_name,
            lang=app_lang,
        )
    except PledgeNotFound as exc:
        raise HTTPException(status_code=404, detail="Pledge not found") from exc
    except ValueError as exc:
        raise _as_http(exc) from exc
    token = str(doc.get("token") or "")
    return {
        "token": token,
        "mile_number": doc.get("mile_number"),
        "mile_quantity": doc.get("mile_quantity"),
        "issue_date": doc.get("issue_date"),
        **public_certificate_links(token),
    }


@router.get("/certificates/{token}.png")
async def get_certificate_png(token: str, lang: Optional[str] = None):
    app_lang = resolve_app_language(lang)
    doc = await load_certificate(token)
    if not doc:
        raise HTTPException(status_code=404, detail="Certificate not found")
    body = render_certificate_png(doc, app_lang)
    return Response(
        content=body,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/certificates/{token}.pdf")
async def get_certificate_pdf(token: str, lang: Optional[str] = None):
    app_lang = resolve_app_language(lang)
    doc = await load_certificate(token)
    if not doc:
        raise HTTPException(status_code=404, detail="Certificate not found")
    body = render_certificate_pdf(doc, app_lang)
    return Response(
        content=body,
        media_type="application/pdf",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/milestones/{milestone_id}/fund")
async def get_fund(milestone_id: str, request: Request):
    """A stopover, cabin-leg, or common fund total is public. The project fund needs the key.

    The body is aggregated money only: no journal lines and no pledge ids.
    """
    bucket = _unplaced_bucket(milestone_id)
    if bucket == "projet" or await _project_fund_target(milestone_id):
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


def _enforce_captain_rate(
    request: Request,
    text: str = "",
    *,
    lang: Optional[str] = None,
) -> None:
    forwarded = request.headers.get("x-forwarded-for", "")
    host = request.client.host if request.client else ""
    session = request.headers.get("x-escales-session", "")
    app_lang = resolve_app_language(lang)
    try:
        hit_captain_rate(captain_rate_key(client_ip(forwarded, host), session))
    except RateLimited as exc:
        raise HTTPException(
            status_code=429,
            detail=limit_message(exc.kind, app_lang, exc.limit),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc


@router.post("/captain/review/{milestone_id}")
async def post_review(milestone_id: str, request: Request, lang: Optional[str] = None):
    app_lang = resolve_app_language(lang)
    _enforce_captain_rate(request, lang=app_lang)
    try:
        proposal = await captain_review(milestone_id, reader=_reader(), lang=app_lang)
    except (PayPalError, ValueError) as exc:
        raise _as_http(exc, lang=app_lang) from exc
    if not _treasurer_privileged(request):
        proposal = {
            key: value
            for key, value in proposal.items()
            if key not in {"pending_authorizations", "pledge_ids"}
        }
    return proposal


@router.post("/milestones/{milestone_id}/captain-review/approve")
async def post_captain_review_approve(milestone_id: str, request: Request):
    _require_treasurer(request)
    try:
        return await record_captain_review_approval(milestone_id)
    except ValueError as exc:
        raise _as_http(exc) from exc


@router.post("/captain/chat")
async def post_chat(body: ChatIn, request: Request):
    app_lang = resolve_app_language(body.lang)
    _enforce_captain_rate(request, body.message, lang=app_lang)
    try:
        return await captain_chat(
            body.message,
            treasurer=_valid_admin_key(request),
            lang=body.lang,
            accept_language=request.headers.get("accept-language", ""),
            reader=_treasurer_reader(request),
        )
    except ValueError as exc:
        raise _as_http(exc, lang=body.lang) from exc


@router.get("/admin/llm-cascade-probe")
async def get_llm_cascade_probe(request: Request):
    """Treasurer-only: which provider answered chat, report, and ask_json. No bodies or keys."""
    _require_treasurer(request)
    return await llm.probe_cascade()


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


from app.routers import wishlists as _wishlists_router

router.include_router(_wishlists_router.router)
