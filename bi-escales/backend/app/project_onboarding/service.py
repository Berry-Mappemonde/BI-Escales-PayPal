"""Business logic for onboard-after-payment (donations, referrals, status)."""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from app.escales.config import (
    demo_project_contact_email,
    load_platform_config,
    onboard_after_payment_enabled,
    order_cancel_url,
    order_return_url,
    paypal_partner_merchant_id,
    public_base_url,
)
from app.escales.ledger import now_iso
from app.escales.paypal_client import PayPalClient, PayPalError, paypal_checkout_locale
from app.project_onboarding.constants import (
    DEMO_PROJECT_ID,
    HELD_DAYS,
    ONBOARDED_STATUS,
    ONBOARDING_HELD_STATUS,
    ONBOARDING_REQUIRED_STATUS,
)
from app.project_onboarding.email_provider import send_html_email
from app.project_onboarding.email_template import render_onboarding_email
from app.project_onboarding.partner_referrals import (
    RawHttpPartnerReferralsClient,
    action_url_from_referral,
    onboarding_return_url,
    referral_self_href,
)
from app.project_onboarding.paypal_orders import (
    capture_order_once,
    capture_status_and_id,
    create_unlinked_payee_capture_order,
    is_unlinked_payee_failure,
    order_approve_url,
    order_belongs_to_donation,
    read_order,
)
from app.project_onboarding.store import (
    get_donation,
    get_project,
    get_referral,
    list_donations,
    save_donation,
    save_project,
    save_referral,
)

log = logging.getLogger("escales.project_onboarding.service")


class DonationCaptureRejected(Exception):
    """Capture blocked before PayPal money movement."""

    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(detail)


def _paypal() -> PayPalClient:
    """Onboarding runs on the PayPal Platform app when it is configured, else on the main app."""
    return PayPalClient(load_platform_config())


def _deadline_from(iso_moment: str) -> str:
    try:
        start = dt.datetime.fromisoformat(iso_moment.replace("Z", "+00:00"))
    except ValueError:
        start = dt.datetime.now(dt.timezone.utc)
    end = start + dt.timedelta(days=HELD_DAYS)
    return end.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_amount(raw: str) -> str:
    try:
        value = Decimal(str(raw or "0"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("amount_eur is invalid") from exc
    if value < Decimal("1.00"):
        raise ValueError("amount_eur must be at least 1.00")
    return f"{value.quantize(Decimal('0.01'))}"


def project_contact_email(project: dict, *, override: str = "") -> str:
    if override:
        return override.strip()
    if str(project.get("_id") or "") == DEMO_PROJECT_ID:
        configured = demo_project_contact_email()
        if configured:
            return configured
    return "project@example.com"


def _localized(project: dict, lang: str) -> dict[str, str]:
    code = "en" if str(lang or "").lower().startswith("en") else "fr"
    title_key = "title_en" if code == "en" else "title_fr"
    description_key = "description_en" if code == "en" else "description_fr"
    foundation_key = "foundation_title_en" if code == "en" else "foundation_title_fr"
    return {
        "lang": code,
        "title": str(project.get(title_key) or project.get("title_fr") or ""),
        "description": str(project.get(description_key) or project.get("description_fr") or ""),
        "foundation_title": str(project.get(foundation_key) or project.get("foundation_title_fr") or ""),
    }


def _is_public_onboarding_project(project_id: str, project: dict) -> bool:
    if str(project_id) == DEMO_PROJECT_ID:
        return True
    return bool(project.get("demo_fake"))


async def public_project_view(project_id: str, *, lang: str = "fr") -> Optional[dict]:
    project = await get_project(project_id)
    if not project or not _is_public_onboarding_project(project_id, project):
        return None
    donations = await list_donations(project_id)
    loc = _localized(project, lang)
    referral = await get_referral(project_id)
    view: dict[str, Any] = {
        "id": project_id,
        "demo_fake": bool(project.get("demo_fake")),
        "title": loc["title"],
        "description": loc["description"],
        "onboarding_status": project.get("onboarding_status") or "pending",
        "onboarded_at": project.get("onboarded_at"),
        "donations": [_public_donation_row(row, lang) for row in donations],
        "onboarding_link": referral.get("action_url") if referral else None,
        "wallet_only": True,
        "card_fields_hidden": True,
    }
    image_url = str(project.get("image_url") or "").strip()
    if image_url:
        view["image_url"] = image_url
    location_label = str(project.get("location_label") or "").strip()
    if location_label:
        view["location_label"] = location_label
    if project.get("lat") is not None:
        view["lat"] = project.get("lat")
    if project.get("lng") is not None:
        view["lng"] = project.get("lng")
    return view


def _public_donation_row(row: dict, lang: str) -> dict:
    status = str(row.get("status") or "")
    code = "en" if str(lang or "").lower().startswith("en") else "fr"
    label_key = status
    return {
        "id": row.get("_id"),
        "amount_eur": row.get("amount_eur"),
        "status": status,
        "status_label_key": f"projectOnboarding.status.{label_key}",
        "deadline_at": row.get("deadline_at"),
        "capture_id": row.get("capture_id"),
        "lang": code,
    }


async def create_donation_order(
    project_id: str,
    *,
    amount_eur: str,
    contributor: str = "",
    lang: str = "fr",
    return_url: str = "",
    cancel_url: str = "",
    contact_override: str = "",
    client: Optional[PayPalClient] = None,
) -> dict:
    if not onboard_after_payment_enabled():
        raise PermissionError("feature disabled")
    project = await get_project(project_id)
    if not project:
        raise LookupError("project not found")
    if project.get("onboarding_status") == ONBOARDED_STATUS:
        raise ValueError("project already onboarded")
    amount = _normalize_amount(amount_eur)
    donation_id = uuid.uuid4().hex
    payee = project_contact_email(project, override=contact_override)
    client = client or _paypal()
    order = create_unlinked_payee_capture_order(
        client,
        amount_eur=amount,
        description=f"Donation {project_id}",
        project_id=project_id,
        payee_email=payee,
        donation_id=donation_id,
        return_url=return_url or order_return_url(),
        cancel_url=cancel_url or order_cancel_url(),
        checkout_locale=paypal_checkout_locale(lang),
    )
    order_id = order.get("id")
    if not order_id:
        raise PayPalError(502, "order id missing")
    doc = {
        "_id": donation_id,
        "project_id": project_id,
        "status": "created",
        "amount_eur": amount,
        "currency": "EUR",
        "contributor": (contributor or "").strip() or None,
        "order_id": order_id,
        "approve_link": order_approve_url(order),
        "created_at": now_iso(),
        "checkout_locale": paypal_checkout_locale(lang),
    }
    saved = await save_donation(doc)
    return await _attach_onboarding_link(saved, project_id, lang=lang, client=client)


async def _attach_onboarding_link(
    payload: dict,
    project_id: str,
    *,
    lang: str = "fr",
    client: Optional[PayPalClient] = None,
) -> dict:
    try:
        referral = await ensure_onboarding_link(project_id, lang=lang, client=client)
        payload["onboarding_link"] = {
            "available": bool(referral.get("action_url")),
            "action_url": referral.get("action_url"),
        }
    except PayPalError as exc:
        log.warning(
            "partner referral unavailable http_status=%s project_id=%s",
            exc.status,
            project_id,
        )
        payload["onboarding_link"] = {
            "available": False,
            "reason": "partner_referrals_unavailable",
            "http_status": exc.status,
        }
    return payload


async def finalize_donation_capture(
    donation_id: str,
    *,
    client: Optional[PayPalClient] = None,
) -> dict:
    donation = await get_donation(donation_id)
    if not donation:
        raise LookupError("donation not found")
    if donation.get("capture_id"):
        return donation
    client = client or _paypal()
    order_id = str(donation.get("order_id") or "")
    if not order_id:
        raise DonationCaptureRejected(400, "donation has no PayPal order")
    try:
        order = read_order(client, order_id)
    except PayPalError as exc:
        if exc.status == 404:
            raise DonationCaptureRejected(404, "PayPal order not found") from exc
        raise
    paypal_status = str(order.get("status") or "").upper()
    if paypal_status != "APPROVED":
        raise DonationCaptureRejected(409, f"order status is {paypal_status or 'UNKNOWN'}, not APPROVED")
    if not order_belongs_to_donation(order, donation):
        raise DonationCaptureRejected(400, "PayPal order does not match this donation")
    try:
        payload = capture_order_once(client, order_id)
        status, capture_id = capture_status_and_id(payload)
        captured_at = now_iso()
        if status in {"COMPLETED", "PENDING"}:
            donation["status"] = ONBOARDING_HELD_STATUS
            donation["capture_id"] = capture_id
            donation["captured_at"] = captured_at
            donation["deadline_at"] = _deadline_from(captured_at)
        else:
            donation["status"] = ONBOARDING_REQUIRED_STATUS
            donation["capture_note"] = status or "UNKNOWN"
    except PayPalError as exc:
        if not is_unlinked_payee_failure(exc):
            raise
        donation["status"] = ONBOARDING_REQUIRED_STATUS
        donation["capture_error_status"] = exc.status
    project_id = str(donation.get("project_id") or "")
    saved = await save_donation(donation)
    return await _attach_onboarding_link(
        saved,
        project_id,
        lang=str(donation.get("checkout_locale") or "fr"),
        client=client,
    )


async def ensure_onboarding_link(
    project_id: str,
    *,
    lang: str = "fr",
    client: Optional[PayPalClient] = None,
    referrals: Optional[RawHttpPartnerReferralsClient] = None,
    contact_override: str = "",
) -> dict:
    project = await get_project(project_id)
    if not project:
        raise LookupError("project not found")
    existing = await get_referral(project_id)
    if existing and existing.get("action_url"):
        return existing
    email = project_contact_email(project, override=contact_override)
    locale = paypal_checkout_locale(lang)
    client = client or _paypal()
    referrals = referrals or RawHttpPartnerReferralsClient(client)
    payload = referrals.create_referral(
        email=email,
        tracking_id=project_id,
        preferred_language_code=locale,
        return_url=onboarding_return_url(project_id),
    )
    referral_id, self_href = referral_self_href(payload)
    action_url = action_url_from_referral(payload)
    doc = {
        "project_id": project_id,
        "partner_referral_id": referral_id,
        "self_href": self_href,
        "action_url": action_url,
        "created_at": now_iso(),
    }
    return await save_referral(doc)


async def refresh_action_url(project_id: str, *, client: Optional[PayPalClient] = None) -> dict:
    referral = await get_referral(project_id)
    if not referral:
        raise LookupError("referral not found")
    token = str(referral.get("partner_referral_id") or "")
    if not token:
        raise ValueError("partner_referral_id missing")
    client = client or _paypal()
    referrals = RawHttpPartnerReferralsClient(client)
    payload = referrals.get_referral(token)
    referral["action_url"] = action_url_from_referral(payload)
    referral["refreshed_at"] = now_iso()
    return await save_referral(referral)


async def email_preview(project_id: str, *, lang: str = "fr", donation_id: str = "") -> dict:
    project = await get_project(project_id)
    if not project:
        raise LookupError("project not found")
    donations = await list_donations(project_id)
    donation = None
    if donation_id:
        donation = await get_donation(donation_id)
    elif donations:
        donation = donations[-1]
    amount = str((donation or {}).get("amount_eur") or "10.00")
    status = str((donation or {}).get("status") or "")
    deadline = (donation or {}).get("deadline_at") if status == ONBOARDING_HELD_STATUS else None
    referral = await get_referral(project_id)
    if referral and referral.get("partner_referral_id"):
        referral = await refresh_action_url(project_id)
    else:
        referral = await ensure_onboarding_link(project_id, lang=lang)
    loc = _localized(project, lang)
    rendered = render_onboarding_email(
        lang=lang,
        amount_eur=amount,
        foundation_name=loc["foundation_title"],
        project_title=loc["title"],
        action_url=str(referral.get("action_url") or ""),
        donation_status=status,
        deadline_iso=str(deadline) if deadline else None,
    )
    return {**rendered, "action_url": referral.get("action_url")}


async def send_onboarding_email(project_id: str, *, lang: str = "fr", donation_id: str = "") -> dict:
    preview = await email_preview(project_id, lang=lang, donation_id=donation_id)
    project = await get_project(project_id)
    if not project:
        raise LookupError("project not found")
    to = project_contact_email(project)
    outcome = await send_html_email(to=to, subject=preview["subject"], html=preview["html"])
    return {**outcome, "to_domain": to.split("@")[-1] if "@" in to else ""}


async def handle_onboarding_return(
    project_id: str,
    *,
    merchant_id_in_paypal: str = "",
    permissions_granted: Optional[bool] = None,
    is_email_confirmed: Optional[bool] = None,
    client: Optional[PayPalClient] = None,
) -> dict:
    project = await get_project(project_id)
    if not project:
        raise LookupError("project not found")
    _ = permissions_granted
    _ = is_email_confirmed
    partner_id = paypal_partner_merchant_id()
    receivable = False
    email_confirmed = False
    integrations: dict[str, Any] = {}
    merchant_verified: Optional[str] = None
    if not partner_id:
        return {
            "project_id": project_id,
            "onboarding_status": project.get("onboarding_status"),
            "payments_receivable": False,
            "primary_email_confirmed": False,
            "merchant_id_in_paypal": None,
            "integrations_summary": False,
            "verified": False,
            "reason": "partner_merchant_id_not_configured",
        }
    client = client or _paypal()
    referrals = RawHttpPartnerReferralsClient(client)
    tracking = referrals.merchant_integrations_by_tracking(partner_id=partner_id, tracking_id=project_id)
    integrations = tracking
    merchant_id = str(tracking.get("merchant_id") or "").strip()
    if merchant_id:
        seller = referrals.merchant_integration_seller_status(partner_id=partner_id, merchant_id=merchant_id)
        integrations = {"tracking": tracking, "seller": seller}
        receivable = bool(seller.get("payments_receivable"))
        email_confirmed = bool(seller.get("primary_email_confirmed"))
        merchant_verified = merchant_id
    else:
        merchant_verified = None
    if receivable and email_confirmed:
        project["onboarding_status"] = ONBOARDED_STATUS
        project["onboarded_at"] = now_iso()
        project["merchant_id"] = merchant_verified
        await save_project(project)
    return {
        "project_id": project_id,
        "onboarding_status": project.get("onboarding_status"),
        "payments_receivable": receivable,
        "primary_email_confirmed": email_confirmed,
        "merchant_id_in_paypal": merchant_verified,
        "integrations_summary": bool(integrations),
        "verified": bool(receivable and email_confirmed),
        "query_merchant_ignored": bool(merchant_id_in_paypal) and merchant_id_in_paypal != merchant_verified,
    }


async def mark_onboarded_from_webhook(project_id: str, *, merchant_id: str = "") -> dict:
    project = await get_project(project_id)
    if not project:
        return {"accepted": False, "reason": "unknown_project"}
    project["onboarding_status"] = ONBOARDED_STATUS
    project["onboarded_at"] = now_iso()
    if merchant_id:
        project["merchant_id"] = merchant_id
    await save_project(project)
    return {"accepted": True, "project_id": project_id}
