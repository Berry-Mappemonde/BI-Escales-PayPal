"""Project payouts: propose first, PayPal batch only after treasurer approval.

Payouts batch API:
https://developer.paypal.com/docs/api/payments.payouts-batch/v1/#payouts_post
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from .app_i18n import normalize_app_lang
from .ledger import _euros, get_ledger, list_finance_entries, record_finance, update_finance_entry
from .paypal_settlement import pledge_spendable_net_eur
from .paypal_client import PayPalError, _paypal_api_error_fields


class PayoutNotFound(LookupError):
    pass


class PayoutStateError(ValueError):
    pass


def _amount(value: str) -> Decimal:
    try:
        amount = Decimal(str(value or "0"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("amount_eur is invalid") from exc
    if amount <= 0:
        raise ValueError("amount_eur must be positive")
    return amount.quantize(Decimal("0.01"))


async def _payout_sent_for_proposal(payout_id: str) -> Optional[dict]:
    for entry in await list_finance_entries():
        if entry.get("kind") != "payout_sent":
            continue
        if str(entry.get("proposal_id") or "") == payout_id:
            return entry
    return None


async def project_captured_eur(project_id: str) -> Decimal:
    """Sum of captured project pledges for one BI project id."""
    pid = str(project_id or "").strip()
    total = Decimal("0.00")
    for row in await get_ledger().list_pledges():
        if str(row.get("kind") or "") != "project_pledge":
            continue
        if str(row.get("target_id") or "") != pid:
            continue
        if str(row.get("status") or "") not in ("captured", "partially_refunded"):
            continue
        total += pledge_spendable_net_eur(row)
    return total


async def project_payout_committed_eur(
    project_id: str,
    *,
    exclude_proposal_id: str = "",
) -> Decimal:
    """Pending proposals plus sent payouts for one project."""
    pid = str(project_id or "").strip()
    skip = str(exclude_proposal_id or "")
    total = Decimal("0.00")
    for entry in await list_finance_entries():
        if str(entry.get("project_id") or "") != pid:
            continue
        if str(entry.get("_id") or "") == skip:
            continue
        if entry.get("kind") == "payout_sent":
            total += _euros(entry.get("amount_eur"))
            continue
        if entry.get("kind") == "payout_proposed" and entry.get("status") == "pending_approval":
            total += _euros(entry.get("amount_eur"))
    return total


async def project_payout_available_eur(project_id: str, *, exclude_proposal_id: str = "") -> Decimal:
    captured = await project_captured_eur(project_id)
    committed = await project_payout_committed_eur(project_id, exclude_proposal_id=exclude_proposal_id)
    return captured - committed


async def find_payout_proposal(payout_id: str) -> dict:
    for entry in await list_finance_entries():
        if str(entry.get("_id") or "") != payout_id:
            continue
        if entry.get("kind") != "payout_proposed":
            continue
        return entry
    raise PayoutNotFound(payout_id)


async def propose_project_payout(
    project_id: str,
    *,
    amount_eur: str,
    receiver_email: str,
    note: str = "",
) -> dict:
    """Record a payout waiting for explicit human approval (no PayPal call)."""
    email = (receiver_email or "").strip()
    if "@" not in email:
        raise ValueError("receiver_email is required")
    amount = _amount(amount_eur)
    pid = str(project_id or "").strip()
    available = await project_payout_available_eur(pid)
    if amount > available:
        raise ValueError(f"payout exceeds captured project funds ({available:.2f} EUR)")
    return await record_finance(
        "payout_proposed",
        project_id=pid,
        amount_eur=f"{amount:.2f}",
        receiver_email=email,
        note=(note or "")[:200],
        status="pending_approval",
    )


def _default_payout_note(project_id: str, lang: Optional[str] = None) -> str:
    app_lang = normalize_app_lang(lang)
    pid = str(project_id or "").strip() or "projet"
    if app_lang == "en":
        return f"Berry-Mappemonde Escales payout for project {pid}"
    return f"Versement Escales Berry-Mappemonde pour le projet {pid}"


async def approve_project_payout(
    payout_id: str,
    client: Any,
    *,
    lang: Optional[str] = None,
) -> dict:
    """Send a previously proposed payout to PayPal. Requires a second human step."""
    proposal = await find_payout_proposal(payout_id)
    status = str(proposal.get("status") or "")
    if status == "failed":
        raise PayoutStateError("payout approval failed")
    if await _payout_sent_for_proposal(payout_id):
        raise PayoutStateError("payout already approved")
    if status != "pending_approval":
        raise PayoutStateError("payout already approved")
    project_id = str(proposal.get("project_id") or "")
    amount = _amount(str(proposal.get("amount_eur") or "0"))
    available = await project_payout_available_eur(project_id, exclude_proposal_id=payout_id)
    if amount > available:
        raise ValueError(f"payout exceeds captured project funds ({available:.2f} EUR)")
    batch_id = f"payout-{payout_id}"
    note = str(proposal.get("note") or "").strip() or _default_payout_note(project_id, lang)
    try:
        payload = client.create_payout(
            batch_id=batch_id,
            receiver_email=str(proposal.get("receiver_email") or ""),
            amount_eur=f"{amount:.2f}",
            note=note,
            item_id=payout_id,
            lang=lang,
        )
    except PayPalError as exc:
        err = _paypal_api_error_fields(exc.body) or {}
        await update_finance_entry(
            payout_id,
            {"status": "failed", "paypal_error": err},
        )
        raise
    batch_header = payload.get("batch_header") if isinstance(payload, dict) else {}
    await update_finance_entry(payout_id, {"status": "approved"})
    return await record_finance(
        "payout_sent",
        proposal_id=payout_id,
        project_id=project_id,
        amount_eur=f"{amount:.2f}",
        receiver_email=proposal.get("receiver_email"),
        payout_batch_id=batch_header.get("payout_batch_id") if isinstance(batch_header, dict) else None,
        status="sent",
        actor="treasurer",
    )
