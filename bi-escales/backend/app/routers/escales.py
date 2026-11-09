"""BI Escales HTTP API, prefix /api/escales.

Registered from ``app.main`` only when ``ESCALES_ENABLED`` is truthy.
Every route also 404s when the flag is off, so a process that imported the
router early still hides it. Capture and void require ``x-admin-key``.
"""
from __future__ import annotations

import os
import secrets
from typing import Annotated, Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from app.openapi_metadata import path_param, query_param, route_docs, with_example
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


def _text(
    description: str,
    example: str,
    title: str,
    *,
    default: Any = ...,
    **constraints: Any,
):
    """Field metadata. Constraints already on the field are passed through."""
    kwargs: dict[str, Any] = {
        "description": description,
        "title": title,
        "examples": [example],
        "json_schema_extra": {"example": example},
    }
    kwargs.update(constraints)
    if default is ...:
        return Field(**kwargs)
    return Field(default, **kwargs)


class CertificateIn(BaseModel):
    """Buyer proof and optional display name for a mile sponsorship certificate."""

    model_config = ConfigDict(
        json_schema_extra=with_example(
            {"payer_proof": "ORDER-example", "display_name": "Ada"}
        )
    )
    payer_proof: Optional[str] = Field(
        None,
        description="PayPal order id or vault setup token id from the buyer checkout response.",
        title="Certificate payer proof",
        examples=["ORDER-example"],
        json_schema_extra={"example": "ORDER-example"},
    )
    display_name: Optional[str] = Field(
        None,
        max_length=120,
        description="Name printed on the mile certificate.",
        title="Certificate display name",
        examples=["Ada"],
        json_schema_extra={"example": "Ada"},
    )


class PledgeIn(BaseModel):
    """Create a sandbox pledge. This route authorizes or vaults; it does not capture."""

    model_config = ConfigDict(
        json_schema_extra=with_example(
            {
                "amount_eur": "20.00",
                "description": "20 milles La Rochelle",
                "milestone_id": "dep-la-rochelle",
                "kind": "mile",
                "quantity": 1,
            }
        )
    )
    quantity: Optional[int] = Field(
        None,
        ge=1,
        le=1000,
        strict=True,
        title="Pledge quantity",
        description="How many simulated units. Omit it to let the server apply the kind default.",
        examples=[1],
        json_schema_extra={"example": 1},
    )
    amount_eur: str = _text("Pledge amount in EUR.", "20.00", "Pledge amount in EUR")
    description: str = _text(
        "Supporter-facing pledge description.",
        "20 milles La Rochelle",
        "Pledge description",
    )
    milestone_id: str = Field(
        "",
        title="Pledge milestone id",
        description=(
            "Where the pledge sits on the route: a stop id (dep-… or ret-…) or a "
            "cabin leg id (leg-…). Empty for project_pledge and common_fund when "
            "no stopover is named. target_id is what the money is for and can "
            "differ: the bare stop slug, the same leg id, or the default projet "
            "or fonds-commun."
        ),
        examples=["dep-la-rochelle"],
        json_schema_extra={"example": "dep-la-rochelle"},
    )
    contributor: Optional[str] = _text(
        "Display name the supporter chooses to share.",
        "Ada",
        "Pledge contributor",
        default=None,
    )
    kind: Optional[str] = _text(
        "Pledge kind such as mile, berth, cabin, project_pledge, or common_fund.",
        "mile",
        "Pledge kind",
        default=None,
    )
    target_id: Optional[str] = Field(
        None,
        title="Pledge target id",
        description=(
            "What the money is for. A stopover kind stores the bare slug of "
            "milestone_id. A cabin stores the leg id, the same value as "
            "milestone_id. project_pledge defaults to projet and common_fund to "
            "fonds-commun when milestone_id is empty."
        ),
        examples=["dep-la-rochelle"],
        json_schema_extra={"example": "dep-la-rochelle"},
    )
    return_url: Optional[str] = _text(
        "Browser URL after the buyer approves the sandbox checkout.",
        "https://bi-escales-api-test2.onrender.com/paypal/return",
        "Pledge return URL",
        default=None,
    )
    cancel_url: Optional[str] = _text(
        "Browser URL when the buyer cancels the sandbox checkout.",
        "https://bi-escales-api-test2.onrender.com/paypal/cancel",
        "Pledge cancel URL",
        default=None,
    )
    lang: Optional[str] = _text(
        "Checkout language, en or fr.",
        "en",
        "Pledge checkout language",
        default=None,
    )
    checkout_method: Optional[str] = Field(
        None,
        title="Pledge checkout method",
        description="wallet (default) or card when ESCALES_CARD_FIELDS_ENABLED is on.",
        examples=["wallet"],
        json_schema_extra={"example": "wallet"},
    )


class EvidenceIn(BaseModel):
    """Treasurer evidence attached to one voyage stop."""

    model_config = ConfigDict(
        json_schema_extra=with_example({"met": True, "facts": {"note": "Alongside in La Rochelle"}})
    )
    met: Optional[bool] = _text(
        "Whether the stop condition is met.",
        True,
        "Evidence met",
        default=None,
    )
    facts: dict = Field(
        default_factory=dict,
        title="Evidence facts",
        description="Free-form facts the treasurer attaches to the stop.",
    )


class ChatIn(BaseModel):
    """Question for the AI Captain. The captain does not move money."""

    model_config = ConfigDict(
        json_schema_extra=with_example(
            {"message": "When is the La Rochelle stop?", "lang": "en"}
        )
    )
    message: str = _text(
        "Supporter question for the AI Captain.",
        "When is the La Rochelle stop?",
        "Captain chat message",
    )
    lang: Optional[str] = _text(
        "Reply language, en or fr.",
        "en",
        "Captain chat language",
        default=None,
    )


class SpendingIn(BaseModel):
    """Treasurer spending line recorded against a stop fund."""

    model_config = ConfigDict(
        json_schema_extra=with_example({"amount_eur": "12.00", "description": "Harbour dues"})
    )
    amount_eur: str = _text("Spending amount in EUR.", "12.00", "Spending amount in EUR")
    description: str = _text("What the spending line paid for.", "Harbour dues", "Spending description")


class RefundIn(BaseModel):
    """Treasurer sandbox refund. Capture is not repeated here."""

    model_config = ConfigDict(
        json_schema_extra=with_example({"amount_eur": "20.00", "request_key": "refund-example"})
    )
    amount_eur: Optional[str] = _text(
        "Refund amount in EUR. Omit it to refund the captured amount.",
        "20.00",
        "Refund amount in EUR",
        default=None,
    )
    now: Optional[str] = _text(
        "Optional simulated-clock moment. Requires ESCALES_CLOCK_NOW.",
        "2026-11-12T12:00:00Z",
        "Refund clock moment",
        default=None,
    )
    request_key: Optional[str] = _text(
        "Idempotency token when the Idempotency-Key header is absent.",
        "refund-example",
        "Refund request key",
        default=None,
    )
    paypal_refund_id: Optional[str] = _text(
        "Existing PayPal sandbox refund id when the treasurer records one.",
        "REFUND-example",
        "PayPal refund id",
        default=None,
    )


class CaptureIn(BaseModel):
    """Optional clock override for a treasurer capture."""

    model_config = ConfigDict(json_schema_extra=with_example({"now": "2026-11-12T12:00:00Z"}))
    now: Optional[str] = _text(
        "Optional simulated-clock moment. Requires ESCALES_CLOCK_NOW.",
        "2026-11-12T12:00:00Z",
        "Capture clock moment",
        default=None,
    )


class ReauthorizeIn(BaseModel):
    """Test-only honor-period reauthorize body."""

    model_config = ConfigDict(json_schema_extra=with_example({"now": "2026-11-12T12:00:00Z"}))
    mock_response: Optional[str] = Field(
        None,
        title="Reauthorize mock response",
        description="Optional PayPal-Mock-Response JSON for sandbox negative testing.",
        examples=['{"mock_application_codes":"INSTRUMENT_DECLINED"}'],
        json_schema_extra={"example": '{"mock_application_codes":"INSTRUMENT_DECLINED"}'},
    )
    now: Optional[str] = Field(
        None,
        title="Reauthorize clock moment",
        description="Optional simulated-clock moment (requires ESCALES_CLOCK_NOW).",
        examples=["2026-11-12T12:00:00Z"],
        json_schema_extra={"example": "2026-11-12T12:00:00Z"},
    )


class PayoutProposeIn(BaseModel):
    """Propose a project payout. PayPal is not called until approve."""

    model_config = ConfigDict(
        json_schema_extra=with_example(
            {
                "amount_eur": "10.00",
                "receiver_email": "marina@example.com",
                "note": "Berth",
            }
        )
    )
    amount_eur: str = _text("Payout amount in EUR.", "10.00", "Payout amount in EUR")
    receiver_email: str = _text(
        "Sandbox receiver email. No live payout is sent from this route.",
        "marina@example.com",
        "Payout receiver email",
    )
    note: str = _text("Note stored with the payout proposal.", "Berth", "Payout proposal note", default="")


class VaultRegisterIn(BaseModel):
    """Setup-token id after the buyer approves a vault. No debit."""

    model_config = ConfigDict(json_schema_extra=with_example({"setup_token_id": "SETUP-example"}))
    setup_token_id: Optional[str] = _text(
        "PayPal setup token id from the buyer vault approval.",
        "SETUP-example",
        "Vault setup token id",
        default=None,
    )


class ClockSettleIn(BaseModel):
    """Optional simulated-clock override for treasurer settlement."""

    model_config = ConfigDict(json_schema_extra=with_example({"now": "2026-11-12T12:00:00Z"}))
    now: Optional[str] = _text(
        "Optional simulated-clock moment. Requires ESCALES_CLOCK_NOW.",
        "2026-11-12T12:00:00Z",
        "Clock settle moment",
        default=None,
    )


class InvoiceCreateIn(BaseModel):
    """Draft a PayPal sandbox invoice. Sending it is a separate treasurer route."""

    model_config = ConfigDict(
        json_schema_extra=with_example(
            {
                "recipient_email": "partner@example.com",
                "amount_eur": "15.00",
                "description": "Harbour dues",
                "lang": "en",
            }
        )
    )
    recipient_email: str = _text(
        "Sandbox recipient email.",
        "partner@example.com",
        "Invoice recipient email",
    )
    amount_eur: str = _text("Invoice amount in EUR.", "15.00", "Invoice amount in EUR")
    description: str = _text("Invoice line description.", "Harbour dues", "Invoice description")
    reference: str = _text("Optional invoice reference.", "harbour-2026-11-12", "Invoice reference", default="")
    invoice_number: Optional[str] = _text(
        "Optional invoice number. PayPal assigns one when this is omitted.",
        "INV-example",
        "Invoice number",
        default=None,
    )
    lang: Optional[str] = _text("Invoice language, en or fr.", "en", "Invoice language", default=None)


class DisputeEvidenceIn(BaseModel):
    """Evidence the treasurer sends to a PayPal sandbox dispute."""

    model_config = ConfigDict(
        json_schema_extra=with_example(
            {"milestone_id": "dep-la-rochelle", "notes": "Arrival logged", "lang": "en"}
        )
    )
    milestone_id: str = _text(
        "Voyage stop the dispute evidence refers to.",
        "dep-la-rochelle",
        "Dispute evidence milestone id",
    )
    notes: Optional[str] = _text(
        "Notes included with the dispute evidence.",
        "Arrival logged",
        "Dispute evidence notes",
        default=None,
    )
    lang: Optional[str] = _text(
        "Language for the dispute evidence, en or fr.",
        "en",
        "Dispute evidence language",
        default=None,
    )


class DisputeAcceptIn(BaseModel):
    """Accept a PayPal sandbox dispute claim."""

    model_config = ConfigDict(json_schema_extra=with_example({"note": "Accepted in sandbox"}))
    note: str = _text(
        "Note sent with the sandbox claim acceptance.",
        "Accepted in sandbox",
        "Dispute acceptance note",
        default="",
    )


class SubscriptionRecordIn(BaseModel):
    """Record a crew subscription the treasurer already sees in PayPal sandbox."""

    model_config = ConfigDict(
        json_schema_extra=with_example(
            {
                "subscription_id": "I-example",
                "plan_id": "P-example",
                "status": "ACTIVE",
                "subscriber_email": "crew@example.com",
            }
        )
    )
    subscription_id: str = _text(
        "PayPal sandbox subscription id to record.",
        "I-example",
        "Recorded subscription id",
    )
    plan_id: str = _text("PayPal sandbox plan id.", "P-example", "Recorded subscription plan id")
    status: str = _text("Subscription status stored locally.", "ACTIVE", "Recorded subscription status", default="ACTIVE")
    subscriber_email: Optional[str] = _text(
        "Subscriber email stored with the local record.",
        "crew@example.com",
        "Recorded subscriber email",
        default=None,
    )


class SubscriptionCreateIn(BaseModel):
    """Buyer return URLs for a crew subscription checkout."""

    model_config = ConfigDict(
        json_schema_extra=with_example(
            {
                "return_url": "https://bi-escales-api-test2.onrender.com/paypal/return",
                "cancel_url": "https://bi-escales-api-test2.onrender.com/paypal/cancel",
                "lang": "en",
            }
        )
    )
    return_url: Optional[str] = _text(
        "Browser URL after the buyer approves the subscription.",
        "https://bi-escales-api-test2.onrender.com/paypal/return",
        "Subscription return URL",
        default=None,
    )
    cancel_url: Optional[str] = _text(
        "Browser URL when the buyer cancels the subscription.",
        "https://bi-escales-api-test2.onrender.com/paypal/cancel",
        "Subscription cancel URL",
        default=None,
    )
    lang: Optional[str] = _text(
        "Subscription checkout language, en or fr.",
        "en",
        "Subscription checkout language",
        default=None,
    )


class SubscriptionApproveIn(BaseModel):
    """Ids from the PayPal sandbox subscription approval."""

    model_config = ConfigDict(
        json_schema_extra=with_example({"subscription_id": "I-example", "plan_id": "P-example"})
    )
    subscription_id: str = _text(
        "PayPal sandbox subscription id the buyer approved.",
        "I-example",
        "Approved subscription id",
    )
    plan_id: str = _text("PayPal sandbox plan id the buyer approved.", "P-example", "Approved subscription plan id")


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


@router.get(
    '/features',
    **route_docs(
        'List feature flags',
        'Public feature flags for the expedition shell.',
        {'card_fields': False},
        schema_description='Feature flags the shell may show. Flags do not move money.',
    ),
)
async def get_features():
    """Public feature flags. No PayPal call."""
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


@router.get(
    '/prices',
    **route_docs(
        'List public prices',
        'Public prices for the simulated catalogue.',
        {'prices': []},
        schema_description='Public price list. No PayPal call.',
    ),
)
async def get_prices():
    """Public prices. No PayPal call."""
    return simulated_prices()


def _clock_body() -> dict:
    return {
        "start": clock_start(),
        "now": simulated_now().replace(microsecond=0).isoformat(),
    }


@router.get(
    '/clock',
    **route_docs(
        'Read the voyage clock',
        'Current simulated voyage clock.',
        {'now': '2026-11-12T12:00:00Z'},
        schema_description='Voyage clock. The reference date is 12 Nov 2026.',
    ),
)
async def get_clock():
    """Public voyage clock. It does not capture or void."""
    return _clock_body()


@router.post(
    '/clock/settle',
    **route_docs(
        'Settle pledges on the voyage clock',
        'Settlement actions for the simulated clock.',
        {'actions': []},
        schema_description='Treasurer settlement result. Capture or void runs only when the clock and review allow it.',
        validation_loc=['body', 'now'],
        body_description='Optional simulated-clock moment for treasurer settlement.',
    ),
)
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


@router.get(
    '/schedule',
    **route_docs(
        'Read the public schedule',
        'Public voyage schedule.',
        {'stops': []},
        schema_description='Public schedule. No PayPal call.',
    ),
)
async def get_schedule():
    """Public voyage schedule. No PayPal call."""
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


@router.post(
    '/schedule/sync',
    **route_docs(
        'Sync the public schedule',
        'Schedule after the sync.',
        {'stops': []},
        schema_description='Schedule sync result. No pledge capture.',
    ),
)
async def post_schedule_sync():
    """Sync the public schedule. No pledge capture."""
    docs = await sync_milestone_shells()
    docs.extend(await sync_leg_shells())
    return [_public_milestone(doc) for doc in docs]


@router.get(
    '/pledges/mode',
    **route_docs(
        'Preview the pledge checkout mode',
        'Read-only checkout mode for one stop or leg.',
        {'kind': 'mile', 'milestone_id': 'dep-la-rochelle', 'checkout_method': 'wallet'},
        schema_description='Checkout mode preview. No PayPal call and no ledger write.',
        validation_loc=['query', 'milestone_id'],
    ),
)
async def get_pledge_mode(milestone_id: Annotated[str, query_param('Stop or leg id whose payment mode is previewed.', 'dep-la-rochelle', 'Pledge mode milestone id')], kind: Annotated[str, query_param('Pledge kind to preview, such as mile.', 'mile', 'Pledge mode kind')] = "mile"):
    """Read-only card checkout preview: no PayPal calls or ledger writes."""
    from app.escales.payment_mode import preview_payment_mode
    try:
        mode = await preview_payment_mode(milestone_id, kind)
        return {"payment_mode": mode}
    except ValueError as exc:
        raise _as_http(exc) from exc


@router.post(
    '/pledges',
    **route_docs(
        'Create a sandbox pledge',
        'Created pledge and the sandbox checkout links.',
        {'status': 'created', 'amount_eur': '20.00'},
        schema_description='Created pledge. The route authorizes or vaults; it does not capture.',
        validation_loc=['body', 'amount_eur'],
        body_description='Pledge to authorize or vault in PayPal sandbox.',
    ),
)
async def post_pledge(body: PledgeIn, request: Request):
    """Create a sandbox pledge. Does not capture funds."""
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


@router.post(
    '/pledges/{pledge_id}/vault',
    **route_docs(
        'Register a vaulted payment method',
        'Pledge after the setup token is stored.',
        {'status': 'vaulted'},
        schema_description='Vault registration result. No debit.',
        validation_loc=['path', 'pledge_id'],
        body_description='Setup token from the buyer vault approval.',
    ),
)
async def post_register_vault(pledge_id: Annotated[str, path_param('Ledger id of the pledge whose payment method is stored.', 'pledge_example', 'Vault pledge id')], body: VaultRegisterIn):
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


@router.post(
    '/pledges/{pledge_id}/authorize',
    **route_docs(
        'Authorize a sandbox pledge',
        'Pledge after the PayPal sandbox authorization.',
        {'status': 'authorized', 'amount_eur': '20.00'},
        schema_description='Public pledge plus the fund aggregate. Capture has not run.',
        validation_loc=['path', 'pledge_id'],
    ),
)
async def post_authorize(pledge_id: Annotated[str, path_param('Ledger id of the pledge to authorize.', 'pledge_example', 'Authorize pledge id')]):
    """Authorize a created PayPal sandbox order. Does not capture funds."""
    try:
        doc = await authorize_pledge(pledge_id, _paypal())
    except (PledgeNotFound, IllegalTransition, PayPalError, ValueError) as exc:
        raise _money_http(exc) from exc
    return await _public_pledge_with_fund(doc)


@router.post(
    '/pledges/{pledge_id}/capture',
    **route_docs(
        'Capture an authorized pledge',
        'Pledge after the treasurer capture.',
        {'status': 'captured', 'amount_eur': '20.00'},
        schema_description='Captured pledge. A human treasurer must call this route.',
        validation_loc=['path', 'pledge_id'],
        body_description='Optional simulated-clock moment for the capture.',
    ),
)
async def post_capture(pledge_id: Annotated[str, path_param('Ledger id of the authorized pledge to capture.', 'pledge_example', 'Capture pledge id')], request: Request, body: CaptureIn = CaptureIn()):
    """Treasurer capture of an authorized sandbox pledge."""
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


@router.post(
    '/pledges/{pledge_id}/void',
    **route_docs(
        'Void an authorized pledge',
        'Pledge after the authorization is voided.',
        {'status': 'voided'},
        schema_description='Voided pledge. Captured funds are not refunded here.',
        validation_loc=['path', 'pledge_id'],
    ),
)
async def post_void(pledge_id: Annotated[str, path_param('Ledger id of the authorized pledge to void.', 'pledge_example', 'Void pledge id')], request: Request):
    """Treasurer void of an authorized sandbox pledge. Does not refund a capture."""
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
    '/pledges/{pledge_id}/refund',
    **route_docs(
        'Refund a captured pledge',
        'Pledge after the sandbox refund.',
        {'status': 'refunded', 'amount_eur': '20.00'},
        schema_description='Refund result for a captured pledge.',
        validation_loc=['path', 'pledge_id'],
        body_description='Refund amount and optional clock or idempotency fields.',
    ),
)
async def post_refund(pledge_id: Annotated[str, path_param('Ledger id of the captured pledge to refund.', 'pledge_example', 'Refund pledge id')], body: RefundIn, request: Request):
    """Treasurer sandbox refund of a captured pledge."""
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
    except (PledgeNotFound, IllegalTransition, PayPalError, ValueError, RefundRequestKeyRequired) as exc:
        raise _money_http(exc) from exc
    return await _public_pledge_with_fund(doc)


@router.post(
    '/admin/pledges/{pledge_id}/reauthorize',
    **route_docs(
        'Reauthorize a pledge in sandbox',
        'Pledge after the test-only reauthorize.',
        {'status': 'authorized'},
        schema_description='Test-only reauthorize result. Hidden when the environment is production.',
        validation_loc=['path', 'pledge_id'],
        body_description='Optional mock response and simulated-clock moment.',
    ),
)
async def post_admin_reauthorize(
    pledge_id: Annotated[str, path_param('Ledger id of the pledge to reauthorize in sandbox.', 'pledge_example', 'Reauthorize pledge id')],
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


@router.get(
    '/paypal/reconcile',
    **route_docs(
        'Reconcile the ledger with PayPal',
        'Read-only reconciliation report.',
        {'rows': []},
        schema_description='Ledger versus PayPal Transaction Search. No capture or void.',
        validation_loc=['query', 'start_date'],
    ),
)
async def get_paypal_reconcile(
    request: Request,
    start_date: Annotated[str, query_param('Inclusive search start date. Voyage clock reference is 12 Nov 2026.', '2026-11-12', 'Reconcile start date')],
    end_date: Annotated[str, query_param('Inclusive search end date.', '2026-11-12', 'Reconcile end date')],
    lang: Annotated[Optional[str], query_param('Report language, en or fr.', 'en', 'Reconcile language')] = None,
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


@router.get(
    '/paypal/disputes',
    **route_docs(
        'List PayPal sandbox disputes',
        'Disputes visible to the treasurer.',
        {'disputes': []},
        schema_description='Sandbox dispute list. No claim is accepted here.',
        validation_loc=['query', 'start_time'],
    ),
)
async def get_paypal_disputes(request: Request, start_time: Annotated[Optional[str], query_param('Only disputes updated at or after this moment.', '2026-11-12T12:00:00Z', 'Dispute search start time')] = None):
    """List PayPal sandbox disputes for the treasurer."""
    _require_treasurer(request)
    try:
        remote = await list_paypal_disputes(_paypal(), start_time=start_time)
        return {"paypal": remote, "snapshots": await list_dispute_snapshots()}
    except PayPalError as exc:
        raise _as_http(exc) from exc


@router.get(
    '/paypal/disputes/{dispute_id}',
    **route_docs(
        'Read one PayPal sandbox dispute',
        'One sandbox dispute.',
        {'dispute_id': 'PP-D-example'},
        schema_description='Sandbox dispute detail.',
        validation_loc=['path', 'dispute_id'],
    ),
)
async def get_paypal_dispute(dispute_id: Annotated[str, path_param('PayPal sandbox dispute id to read.', 'PP-D-example', 'Dispute id to read')], request: Request):
    """Read one PayPal sandbox dispute."""
    _require_treasurer(request)
    try:
        return await get_dispute(_paypal(), dispute_id)
    except PayPalError as exc:
        raise _as_http(exc) from exc


@router.post(
    '/paypal/disputes/{dispute_id}/accept-claim',
    **route_docs(
        'Accept a sandbox dispute claim',
        'Dispute after the claim is accepted.',
        {'dispute_id': 'PP-D-example', 'status': 'RESOLVED'},
        schema_description='Sandbox claim acceptance. This does not capture a pledge.',
        validation_loc=['path', 'dispute_id'],
        body_description='Note sent with the sandbox claim acceptance.',
    ),
)
async def post_dispute_accept(dispute_id: Annotated[str, path_param('PayPal sandbox dispute id whose claim is accepted.', 'PP-D-example', 'Dispute id to accept')], body: DisputeAcceptIn, request: Request):
    """Accept a PayPal sandbox dispute claim."""
    _require_treasurer(request)
    try:
        return await accept_dispute_claim(_paypal(), dispute_id, note=body.note)
    except PayPalError as exc:
        raise _as_http(exc) from exc


@router.post(
    '/paypal/disputes/{dispute_id}/provide-evidence',
    **route_docs(
        'Provide sandbox dispute evidence',
        'Dispute after evidence is sent.',
        {'dispute_id': 'PP-D-example'},
        schema_description='Sandbox dispute evidence result.',
        validation_loc=['path', 'dispute_id'],
        body_description='Stop id and notes sent as sandbox dispute evidence.',
    ),
)
async def post_dispute_evidence(dispute_id: Annotated[str, path_param('PayPal sandbox dispute id that receives the evidence.', 'PP-D-example', 'Dispute id for evidence')], body: DisputeEvidenceIn, request: Request):
    """Send voyage-stop evidence to a PayPal sandbox dispute."""
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


@router.get(
    '/paypal/invoices',
    **route_docs(
        'List PayPal sandbox invoices',
        'One page of sandbox invoices.',
        {'invoices': []},
        schema_description='Sandbox invoice page.',
        validation_loc=['query', 'page'],
    ),
)
async def get_paypal_invoices(request: Request, page: Annotated[int, query_param('1-based invoice page.', 1, 'Invoice list page')] = 1):
    """List PayPal sandbox invoices for the treasurer."""
    _require_treasurer(request)
    try:
        return await list_treasurer_invoices(_paypal(), page=page)
    except PayPalError as exc:
        raise _as_http(exc) from exc


@router.post(
    '/paypal/invoices',
    **route_docs(
        'Create a sandbox invoice draft',
        'Created sandbox invoice draft.',
        {'invoice_id': 'INV-example', 'status': 'DRAFT'},
        schema_description='Draft invoice. Sending it is a separate route.',
        validation_loc=['body', 'recipient_email'],
        body_description='Recipient, amount, and description for the draft invoice.',
    ),
)
async def post_paypal_invoice(body: InvoiceCreateIn, request: Request):
    """Create a PayPal sandbox invoice draft. Does not send it."""
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


@router.post(
    '/paypal/invoices/{invoice_id}/send',
    **route_docs(
        'Send a sandbox invoice',
        'Invoice after it is sent.',
        {'invoice_id': 'INV-example', 'status': 'SENT'},
        schema_description='Sent sandbox invoice.',
        validation_loc=['path', 'invoice_id'],
    ),
)
async def post_invoice_send(invoice_id: Annotated[str, path_param('PayPal sandbox invoice id to send.', 'INV-example', 'Invoice id to send')], request: Request):
    """Send a PayPal sandbox invoice draft."""
    _require_treasurer(request)
    try:
        return await send_invoice(_paypal(), invoice_id)
    except PayPalError as exc:
        raise _as_http(exc) from exc


@router.post(
    '/paypal/invoices/{invoice_id}/remind',
    **route_docs(
        'Remind a sandbox invoice',
        'Invoice after the reminder is sent.',
        {'invoice_id': 'INV-example'},
        schema_description='Sandbox invoice reminder result.',
        validation_loc=['path', 'invoice_id'],
    ),
)
async def post_invoice_remind(
    invoice_id: Annotated[str, path_param('PayPal sandbox invoice id to remind.', 'INV-example', 'Invoice id to remind')],
    request: Request,
    lang: Annotated[Optional[str], query_param('Reminder language, en or fr.', 'en', 'Invoice reminder language')] = None,
):
    """Send a reminder for a PayPal sandbox invoice."""
    _require_treasurer(request)
    app_lang = resolve_app_language(lang)
    try:
        return await remind_invoice(_paypal(app_lang), invoice_id, lang=app_lang)
    except PayPalError as exc:
        raise _as_http(exc, lang=app_lang) from exc


@router.post(
    '/paypal/invoices/{invoice_id}/cancel',
    **route_docs(
        'Cancel a sent sandbox invoice',
        'Invoice after it is cancelled.',
        {'invoice_id': 'INV-example', 'status': 'CANCELLED'},
        schema_description='Cancelled sandbox invoice.',
        validation_loc=['path', 'invoice_id'],
    ),
)
async def post_invoice_cancel(invoice_id: Annotated[str, path_param('PayPal sandbox invoice id to cancel.', 'INV-example', 'Invoice id to cancel')], request: Request):
    """Cancel a sent PayPal sandbox invoice."""
    _require_treasurer(request)
    try:
        return await cancel_invoice(_paypal(), invoice_id)
    except PayPalError as exc:
        raise _as_http(exc) from exc


@router.delete(
    '/paypal/invoices/{invoice_id}',
    **route_docs(
        'Delete a draft sandbox invoice',
        'Invoice after the draft is deleted.',
        {'invoice_id': 'INV-example', 'deleted': True},
        schema_description='Deleted draft invoice. PayPal only cancels invoices that were already sent.',
        validation_loc=['path', 'invoice_id'],
    ),
)
async def delete_invoice_route(invoice_id: Annotated[str, path_param('PayPal sandbox draft invoice id to delete.', 'INV-example', 'Invoice id to delete')], request: Request):
    """Remove a draft invoice (PayPal only cancels sent invoices)."""
    _require_treasurer(request)
    try:
        return await delete_draft_invoice(_paypal(), invoice_id)
    except PayPalError as exc:
        raise _as_http(exc) from exc


@router.post(
    '/paypal/subscriptions/setup',
    **route_docs(
        'Set up the crew subscription plan',
        'Crew supporter product and monthly plan.',
        {'plan_id': 'P-example'},
        schema_description='Idempotent sandbox product and plan. No buyer is charged here.',
    ),
)
async def post_subscription_setup(request: Request):
    """Idempotent Crew supporter product + monthly EUR plan (admin)."""
    _require_treasurer(request)
    try:
        return await ensure_crew_supporter_catalog(_paypal())
    except PayPalError as exc:
        raise _as_http(exc) from exc


@router.get(
    '/paypal/subscriptions/plan',
    **route_docs(
        'Read the crew subscription plan',
        'Public crew supporter plan id.',
        {'plan_id': 'P-example'},
        schema_description='Read-only billing plan. No subscription is created.',
        validation_loc=['query', 'lang'],
    ),
)
async def get_crew_subscription_plan(lang: Annotated[Optional[str], query_param('Plan language, en or fr.', 'en', 'Subscription plan language')] = None):
    """Public read-only Crew supporter billing plan id (hydrates from PayPal when needed)."""
    app_lang = resolve_app_language(lang)
    try:
        plan_id = await resolve_crew_supporter_plan_id(_paypal(app_lang), lang=app_lang)
    except PayPalError as exc:
        raise _as_http(exc, lang=app_lang) from exc
    return {"plan_id": plan_id, "lang": app_lang}


@router.post(
    '/paypal/subscriptions/create',
    **route_docs(
        'Start a crew subscription checkout',
        'Sandbox subscription checkout for the buyer.',
        {'subscription_id': 'I-example'},
        schema_description='Subscription checkout. Approval is recorded on a separate route.',
        validation_loc=['body', 'return_url'],
        body_description='Optional return and cancel URLs for the buyer.',
    ),
)
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


@router.get(
    '/paypal/subscriptions',
    **route_docs(
        'List recorded crew subscriptions',
        'Subscriptions stored for the treasurer.',
        {'subscriptions': []},
        schema_description='Local subscription records. No new PayPal subscription is created.',
    ),
)
async def get_paypal_subscriptions(request: Request):
    """List crew subscriptions stored for the treasurer."""
    _require_treasurer(request)
    return {"items": await list_subscriptions_local()}


@router.post(
    '/paypal/subscriptions/record',
    **route_docs(
        'Record a crew subscription',
        'Subscription stored from PayPal sandbox.',
        {'subscription_id': 'I-example', 'status': 'ACTIVE'},
        schema_description='Local record of a subscription the treasurer already sees in sandbox.',
        validation_loc=['body', 'subscription_id'],
        body_description='Subscription id, plan id, and status to store.',
    ),
)
async def post_subscription_record(body: SubscriptionRecordIn, request: Request):
    """Record a crew subscription the treasurer already sees in PayPal sandbox."""
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


@router.post(
    '/paypal/subscriptions/approve',
    **route_docs(
        'Record an approved crew subscription',
        'Subscription after the buyer approval.',
        {'subscription_id': 'I-example', 'status': 'APPROVED'},
        schema_description='Local record after the buyer approves in PayPal sandbox.',
        validation_loc=['body', 'subscription_id'],
        body_description='Subscription id and plan id from the buyer approval.',
    ),
)
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


@router.get(
    '/gear',
    **route_docs(
        'List expedition gear projects',
        'Public gear projects.',
        {'projects': []},
        schema_description='Gear catalogue. Sandbox seed plus Channel3 search when that flag is on.',
    ),
)
async def get_public_gear_list():
    """Expedition Gear projects (sandbox seed + optional Channel3 search when enabled)."""
    payload = await get_gear_feature_collection()
    return await sanitize_public_gear_collection(payload)


@router.get(
    '/projects/{project_id}/fund',
    **route_docs(
        'Read one project fund',
        'Public totals for one project.',
        {'project_id': 'gear-c3-gf8pnpl', 'amount_eur': '0.00'},
        schema_description='Public crowdfunding totals. The pledge list is omitted.',
        validation_loc=['path', 'project_id'],
    ),
)
async def get_public_project_fund(project_id: Annotated[str, path_param('Project slug whose public fund totals are returned.', 'gear-c3-gf8pnpl', 'Project fund project id')]):
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


@router.get(
    '/common-fund/fund',
    **route_docs(
        'Read the common fund',
        'Public boat common-fund totals.',
        {'target_id': 'fonds-commun', 'amount_eur': '0.00'},
        schema_description='Public common-fund totals. The pledge list is omitted.',
    ),
)
async def get_public_common_fund():
    """Public boat common-fund totals (pattern: ``GET /projects/{id}/fund`` from N33)."""
    try:
        return to_public_fund(await fund_for_milestone("fonds-commun"))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Common fund not found") from exc


@router.post(
    '/projects/{project_id}/payouts',
    **route_docs(
        'Propose a project payout',
        'Payout proposal before PayPal is called.',
        {'payout_id': 'payout_example', 'amount_eur': '10.00'},
        schema_description='Stored payout proposal. PayPal is not called until approve.',
        validation_loc=['path', 'project_id'],
        body_description='Amount, sandbox receiver, and note for the proposal.',
    ),
)
async def post_project_payout(project_id: Annotated[str, path_param('Project slug the payout proposal belongs to.', 'gear-c3-gf8pnpl', 'Payout project id')], body: PayoutProposeIn, request: Request):
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


@router.post(
    '/payouts/{payout_id}/approve',
    **route_docs(
        'Approve a project payout',
        'Payout after it is sent to PayPal sandbox.',
        {'payout_id': 'payout_example', 'status': 'sent'},
        schema_description='Second human step. The payout is sent to PayPal sandbox.',
        validation_loc=['path', 'payout_id'],
    ),
)
async def post_payout_approve(payout_id: Annotated[str, path_param('Payout proposal id to send to PayPal sandbox.', 'payout_example', 'Payout id to approve')], request: Request, lang: Annotated[Optional[str], query_param('Payout language, en or fr.', 'en', 'Payout approval language')] = None):
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


@router.get(
    '/pledges',
    **route_docs(
        'List pledges',
        'Pledges visible to this caller.',
        {'pledges': []},
        schema_description='Pledge list. A treasurer key sees every pledge. A sandbox demo session stays redacted.',
    ),
)
async def get_pledges(request: Request):
    """Every pledge on the server. The key sees everything; a sandbox demo session sees a
    redacted list (status and amounts, never contributor names or PayPal ids)."""
    keyed = _require_treasurer_or_demo(request)
    docs = await get_ledger().list_pledges()
    rows = [_public_pledge(doc) for doc in docs]
    return rows if keyed else [_demo_pledge_row(row) for row in rows]


@router.get(
    '/pledges/{pledge_id}',
    **route_docs(
        'Read one pledge',
        'One pledge visible to this caller.',
        {'pledge_id': 'pledge_example', 'status': 'authorized', 'amount_eur': '20.00'},
        schema_description='Public read is status, amount, and the fund aggregate. The treasurer key sees the pledge.',
        validation_loc=['path', 'pledge_id'],
    ),
)
async def get_pledge(pledge_id: Annotated[str, path_param('Ledger id of the pledge to read.', 'pledge_example', 'Read pledge id')], request: Request):
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


@router.post(
    '/pledges/{pledge_id}/certificate',
    **route_docs(
        'Issue a mile certificate',
        'Certificate token after a successful mile pledge.',
        {'token': 'cert_example'},
        schema_description='Issued once. The PNG and PDF routes serve the bytes.',
        validation_loc=['path', 'pledge_id'],
        body_description='Optional payer proof and the name printed on the certificate.',
    ),
)
async def post_pledge_certificate(
    pledge_id: Annotated[str, path_param('Ledger id of the mile pledge that receives the certificate.', 'pledge_example', 'Certificate pledge id')],
    lang: Annotated[Optional[str], query_param('Certificate language, en or fr.', 'en', 'Certificate language')] = None,
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


@router.get(
    '/certificates/{token}.png',
    **route_docs(
        'Download a certificate PNG',
        'Certificate image bytes.',
        schema_description='Runtime body is image/png. This schema stays the generated object because the handler returns a Response.',
        validation_loc=['path', 'token'],
    ),
)
async def get_certificate_png(token: Annotated[str, path_param('Token from the certificate issue response.', 'cert_example', 'Certificate PNG token')], lang: Annotated[Optional[str], query_param('Certificate language, en or fr.', 'en', 'Certificate PNG language')] = None):
    """Return the mile certificate as a PNG. The response body is image/png."""
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


@router.get(
    '/certificates/{token}.pdf',
    **route_docs(
        'Download a certificate PDF',
        'Certificate document bytes.',
        schema_description='Runtime body is application/pdf. This schema stays the generated object because the handler returns a Response.',
        validation_loc=['path', 'token'],
    ),
)
async def get_certificate_pdf(token: Annotated[str, path_param('Token from the certificate issue response.', 'cert_example', 'Certificate PDF token')], lang: Annotated[Optional[str], query_param('Certificate language, en or fr.', 'en', 'Certificate PDF language')] = None):
    """Return the mile certificate as a PDF. The response body is application/pdf."""
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


@router.get(
    '/milestones/{milestone_id}/fund',
    **route_docs(
        'Read a stop fund',
        'Public fund totals for one stop, leg, or the common fund.',
        {'milestone_id': 'dep-la-rochelle', 'amount_eur': '0.00'},
        schema_description='Public totals. A project fund requires the treasurer key. The pledge list is omitted.',
        validation_loc=['path', 'milestone_id'],
    ),
)
async def get_fund(milestone_id: Annotated[str, path_param('Stop id, cabin leg id, or common fund id.', 'dep-la-rochelle', 'Stop fund milestone id')], request: Request):
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


@router.post(
    '/milestones/{milestone_id}/fund/spending',
    **route_docs(
        'Record spending against a stop fund',
        'Fund after the spending line is stored.',
        {'milestone_id': 'dep-la-rochelle', 'amount_eur': '12.00'},
        schema_description='Treasurer spending line. PayPal is not called.',
        validation_loc=['path', 'milestone_id'],
        body_description='Amount and description of the spending line.',
    ),
)
async def post_spending(milestone_id: Annotated[str, path_param('Stop or leg id the spending line is recorded against.', 'dep-la-rochelle', 'Spending milestone id')], body: SpendingIn, request: Request):
    """Record a treasurer spending line. PayPal is not called."""
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


@router.get(
    '/milestones',
    **route_docs(
        'List voyage stops',
        'Public voyage stops.',
        {'milestones': []},
        schema_description='Voyage stops. No PayPal call.',
    ),
)
async def get_milestones():
    """List public voyage stops. No PayPal call."""
    docs = await list_milestones()
    if not docs:
        docs = await sync_milestone_shells()
    return [_public_milestone(doc) for doc in docs]


@router.post(
    '/milestones/{milestone_id}/evidence',
    **route_docs(
        'Attach evidence to a voyage stop',
        'Stop after the evidence is stored.',
        {'milestone_id': 'dep-la-rochelle', 'met': True},
        schema_description='Treasurer evidence. The AI Captain does not capture or void.',
        validation_loc=['path', 'milestone_id'],
        body_description='Whether the stop condition is met, plus free-form facts.',
    ),
)
async def post_evidence(milestone_id: Annotated[str, path_param('Stop or leg id the evidence is attached to.', 'dep-la-rochelle', 'Evidence milestone id')], body: EvidenceIn, request: Request):
    """Attach treasurer evidence to a voyage stop. Does not move money."""
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


@router.post(
    '/captain/review/{milestone_id}',
    **route_docs(
        'Ask the AI Captain to review a stop',
        'Captain review proposal for the stop.',
        {'milestone_id': 'dep-la-rochelle', 'approved': False},
        schema_description='Advisory review. The captain does not capture or void.',
        validation_loc=['path', 'milestone_id'],
    ),
)
async def post_review(milestone_id: Annotated[str, path_param('Stop or leg id the captain reviews.', 'dep-la-rochelle', 'Captain review milestone id')], request: Request, lang: Annotated[Optional[str], query_param('Review language, en or fr.', 'en', 'Captain review language')] = None):
    """Ask the AI Captain for an advisory review. The captain does not move money."""
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


@router.post(
    '/milestones/{milestone_id}/captain-review/approve',
    **route_docs(
        'Record the captain review approval',
        'Stop after the review approval is stored.',
        {'milestone_id': 'dep-la-rochelle', 'captain_review_approved_at': '2026-11-12T12:00:00Z'},
        schema_description='Stored approval timestamp. Capture still requires the treasurer.',
        validation_loc=['path', 'milestone_id'],
    ),
)
async def post_captain_review_approve(milestone_id: Annotated[str, path_param('Stop or leg id whose captain review is approved.', 'dep-la-rochelle', 'Captain approval milestone id')], request: Request):
    """Record the captain review approval. Does not capture or void."""
    _require_treasurer(request)
    try:
        return await record_captain_review_approval(milestone_id)
    except ValueError as exc:
        raise _as_http(exc) from exc


@router.post(
    '/captain/chat',
    **route_docs(
        'Ask the AI Captain',
        'Captain reply.',
        {'reply': 'The La Rochelle stop is the voyage clock reference, 12 Nov 2026.'},
        schema_description='Advisory reply. The captain does not move money.',
        validation_loc=['body', 'message'],
        body_description='Supporter question for the AI Captain.',
    ),
)
async def post_chat(body: ChatIn, request: Request):
    """Ask the AI Captain a question. The captain does not move money."""
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


@router.get(
    '/admin/llm-cascade-probe',
    **route_docs(
        'Probe the captain model cascade',
        'Which provider answered. No prompt bodies.',
        {'chat': 'ok'},
        schema_description='Treasurer probe. No prompt text and no API keys.',
    ),
)
async def get_llm_cascade_probe(request: Request):
    """Treasurer-only: which provider answered chat, report, and ask_json. No bodies or keys."""
    _require_treasurer(request)
    return await llm.probe_cascade()


@webhooks_router.get(
    '/webhooks/recent',
    **route_docs(
        'List recent PayPal webhook attempts',
        'Recent webhook attempts.',
        {'events': []},
        schema_description='Read-only webhook log. Treasurer key required.',
    ),
)
async def get_recent_webhooks(request: Request):
    """Read-only list of webhook attempts. Treasurer key, same check as capture."""
    _require_treasurer(request)
    return {"events": await list_webhook_outcomes()}


@webhooks_router.post(
    '/webhooks/paypal',
    **route_docs(
        'Receive a PayPal sandbox webhook',
        'Webhook accepted.',
        {'ok': True},
        schema_description='Webhook intake. The handler verifies the sandbox transmission before any ledger update.',
    ),
)
async def post_paypal_webhook(request: Request):
    """Receive a PayPal sandbox webhook. Verification runs before any ledger update."""
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
