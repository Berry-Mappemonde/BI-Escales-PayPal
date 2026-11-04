"""Invoicing v2 — draft, send, remind, cancel (admin); treasurer read-only list."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from .app_i18n import normalize_app_lang
from .ledger import record_finance

_INVOICE_DEFAULT_DESC = {
    "en": "Escales partner invoice",
    "fr": "Facture partenaire Escales",
}
_REMIND_SUBJECT = {
    "en": "Reminder: Escales invoice",
    "fr": "Rappel : facture Escales",
}
_REMIND_NOTE = {
    "en": "Please complete payment.",
    "fr": "Merci de finaliser le paiement.",
}


class InvoiceNotFound(LookupError):
    pass


def _amount(value: str) -> str:
    try:
        amount = Decimal(str(value or "0"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("amount_eur is invalid") from exc
    if amount <= 0:
        raise ValueError("amount_eur must be positive")
    return f"{amount.quantize(Decimal('0.01')):.2f}"


async def create_partner_invoice(
    client: Any,
    *,
    recipient_email: str,
    amount_eur: str,
    description: str,
    reference: str,
    invoice_number: Optional[str] = None,
    lang: Optional[str] = None,
) -> dict:
    app_lang = normalize_app_lang(lang)
    email = (recipient_email or "").strip()
    if not email or "@" not in email:
        raise ValueError("recipient_email is required")
    value = _amount(amount_eur)
    desc = (description or _INVOICE_DEFAULT_DESC[app_lang])[:127]
    ref = (reference or desc)[:127]
    payload = client.create_invoice(
        recipient_email=email,
        amount_eur=value,
        description=desc,
        reference=ref,
        invoice_number=invoice_number,
        lang=app_lang,
    )
    invoice_id = str(payload.get("id") or payload.get("href", "").split("/")[-1] or "")
    await record_finance(
        "paypal_invoice_local",
        invoice_id=invoice_id,
        status="DRAFT",
        recipient_email=email,
        amount_eur=value,
        description=desc,
        reference=ref,
    )
    return payload


async def send_invoice(client: Any, invoice_id: str) -> dict:
    invoice_id = str(invoice_id or "").strip()
    if not invoice_id:
        raise ValueError("invoice_id is required")
    result = client.send_invoice(invoice_id)
    await record_finance("paypal_invoice_action", invoice_id=invoice_id, action="send")
    return result


async def remind_invoice(client: Any, invoice_id: str, *, lang: Optional[str] = None) -> dict:
    invoice_id = str(invoice_id or "").strip()
    if not invoice_id:
        raise ValueError("invoice_id is required")
    app_lang = normalize_app_lang(lang)
    result = client.remind_invoice(
        invoice_id,
        subject=_REMIND_SUBJECT[app_lang],
        note=_REMIND_NOTE[app_lang],
    )
    await record_finance("paypal_invoice_action", invoice_id=invoice_id, action="remind")
    return result


async def cancel_invoice(client: Any, invoice_id: str) -> dict:
    invoice_id = str(invoice_id or "").strip()
    if not invoice_id:
        raise ValueError("invoice_id is required")
    result = client.cancel_invoice(invoice_id)
    await record_finance("paypal_invoice_action", invoice_id=invoice_id, action="cancel")
    return result


async def delete_draft_invoice(client: Any, invoice_id: str) -> dict:
    invoice_id = str(invoice_id or "").strip()
    if not invoice_id:
        raise ValueError("invoice_id is required")
    result = client.delete_invoice(invoice_id)
    await record_finance(
        "paypal_invoice_action",
        invoice_id=invoice_id,
        action="delete_draft",
    )
    return result


async def list_treasurer_invoices(client: Any, *, page: int = 1) -> dict:
    remote = client.list_invoices(page=page)
    items = remote.get("items") if isinstance(remote, dict) else []
    local = await list_invoice_local()
    return {"paypal": remote, "local": local, "items": items}


async def list_invoice_local() -> list[dict]:
    from .ledger import list_finance_entries

    rows: list[dict] = []
    for entry in await list_finance_entries():
        if entry.get("kind") != "paypal_invoice_local":
            continue
        rows.append({
            "invoice_id": entry.get("invoice_id"),
            "status": entry.get("status"),
            "amount_eur": entry.get("amount_eur"),
            "recipient_email": entry.get("recipient_email"),
            "description": entry.get("description"),
            "at": entry.get("at"),
        })
    return rows
