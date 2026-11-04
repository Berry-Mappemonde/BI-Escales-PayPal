"""Project payouts: propose first, PayPal batch only after treasurer approval.

Payouts batch API:
https://developer.paypal.com/docs/api/payments.payouts-batch/v1/#payouts_post
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from .ledger import list_finance_entries, record_finance


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
    return await record_finance(
        "payout_proposed",
        project_id=str(project_id or "").strip(),
        amount_eur=f"{amount:.2f}",
        receiver_email=email,
        note=(note or "")[:200],
        status="pending_approval",
    )


async def approve_project_payout(payout_id: str, client: Any) -> dict:
    """Send a previously proposed payout to PayPal. Requires a second human step."""
    proposal = await find_payout_proposal(payout_id)
    if str(proposal.get("status") or "") != "pending_approval":
        raise PayoutStateError("payout is not pending approval")
    batch_id = f"payout-{payout_id}"
    payload = client.create_payout(
        batch_id=batch_id,
        receiver_email=str(proposal.get("receiver_email") or ""),
        amount_eur=str(proposal.get("amount_eur") or "0.00"),
        note=str(proposal.get("note") or ""),
        item_id=payout_id,
    )
    batch_header = payload.get("batch_header") if isinstance(payload, dict) else {}
    return await record_finance(
        "payout_sent",
        proposal_id=payout_id,
        project_id=proposal.get("project_id"),
        amount_eur=proposal.get("amount_eur"),
        receiver_email=proposal.get("receiver_email"),
        payout_batch_id=batch_header.get("payout_batch_id") if isinstance(batch_header, dict) else None,
        status="sent",
        actor="treasurer",
    )
