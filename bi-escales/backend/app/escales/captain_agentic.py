"""Agentic PayPal flows for the Captain (proposal only until human confirm)."""
from __future__ import annotations

import re
from typing import Any, Optional

_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_AMOUNT = re.compile(r"(\d+(?:[.,]\d{1,2})?)\s*(?:€|eur|euros?)?", re.I)


def _parse_amount(text: str) -> Optional[str]:
    match = _AMOUNT.search(text)
    if not match:
        return None
    raw = match.group(1).replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return None
    return f"{value:.2f}"


def parse_agentic_proposal(message: str, lang: str) -> Optional[dict[str, Any]]:
    """Return a treasurer-only proposed PayPal action (never executes PayPal)."""
    text = (message or "").strip()
    if not text:
        return None
    lower = text.casefold()
    if re.search(r"\b(?:cr[ée]er|create)\b.{0,30}\b(?:facture|invoice)\b", lower):
        email = _EMAIL.search(text)
        amount = _parse_amount(text)
        if not email or not amount:
            return None
        desc_fr = "Facture Escales (sandbox)"
        desc_en = "Escales invoice (sandbox)"
        return {
            "kind": "create_invoice",
            "requires_confirm": True,
            "preview": {
                "recipient_email": email.group(0),
                "amount_eur": amount,
                "description": desc_en if lang == "en" else desc_fr,
            },
            "toolkit_note": "PayPal Agent Toolkit: invoices.create requires treasurer confirm in UI.",
        }
    if re.search(r"\b(?:cr[ée]er|create)\b.{0,30}\b(?:commande|order)\b", lower):
        amount = _parse_amount(text)
        if not amount:
            return None
        return {
            "kind": "create_pledge_order",
            "requires_confirm": True,
            "preview": {
                "amount_eur": amount,
                "description": "Captain proposed order (use pledge button after confirm)",
            },
            "toolkit_note": "orders.create is not auto-run; use Escales pledge flow after review.",
        }
    return None


def agentic_reply(proposal: dict[str, Any], lang: str) -> str:
    kind = str(proposal.get("kind") or "")
    preview = proposal.get("preview") or {}
    if kind == "create_invoice":
        if lang == "en":
            return (
                f"I can draft invoice {preview.get('amount_eur')} EUR to {preview.get('recipient_email')}. "
                "Confirm below — nothing is sent until you approve."
            )
        return (
            f"Je peux préparer une facture de {preview.get('amount_eur')} EUR pour {preview.get('recipient_email')}. "
            "Confirmez ci-dessous — rien n’est envoyé sans votre accord."
        )
    if lang == "en":
        return "I parsed an order proposal. Confirm, then use the pledge button with the suggested amount."
    return "Proposition de commande analysée. Confirmez, puis utilisez le bouton de promesse."


def agentic_suggested_pledge(proposal: dict[str, Any], lang: str) -> Optional[dict[str, Any]]:
    if str(proposal.get("kind") or "") != "create_pledge_order":
        return None
    preview = proposal.get("preview") or {}
    amount = str(preview.get("amount_eur") or "").strip()
    if not amount:
        return None
    return {
        "amount_eur": amount,
        "description": "Promesse proposée par le Capitaine" if lang != "en" else "Captain proposed pledge",
        "milestone_id": "dep-mayotte",
        "kind": "mile",
    }
