"""Captain: composes a pledge in chat and proposes capture or void.

This module never imports the PayPal client. It cannot capture or void.
A proposal is a recommendation for the treasurer, written to escales_audit.
Prices come from the catalogue below, not from the model.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from .config import membership_url
from .milestones import decision_for, filter_numbers, get_milestone, latest_trusted_evidence
from .pledges import get_ledger, now_iso, pledges_for_milestone
from .toolkit_tools import ReadOnlyTools

# Bureau prices. The model is not allowed to invent another tariff.
MILE_EUR = Decimal("1.00")
DINNER_EUR = Decimal("60.00")

_MILES = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:milles?|miles?|nm)\b", re.IGNORECASE)
_DINNER = re.compile(r"d[iî]ners?|dinner", re.IGNORECASE)
_PLACE = re.compile(
    r"(?:près de|pres de|près d'|pres d'|near)\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ-]{1,40})",
    re.IGNORECASE,
)

_REPORT_SYSTEM = (
    "You are the Blue Intelligence Escales captain. Write a short report in French. "
    "Mention only numbers that appear in the evidence JSON. "
    "You never capture, void, or move money. "
    "The treasurer alone can capture or void a pledge."
)
_CHAT_SYSTEM = (
    "You are the Blue Intelligence Escales captain. Help the contributor phrase a pledge. "
    "Do not create an order and do not invent prices. "
    "Mention membership only with the HelloAsso URL you were given. "
    "Mention only numbers present in the suggested pledge or the contributor message."
)


def _place(message: str) -> str:
    match = _PLACE.search(message or "")
    if not match:
        return "unspecified"
    slug = re.sub(r"[^a-z0-9]+", "-", match.group(1).lower()).strip("-")
    return slug or "unspecified"


def suggest_pledge(message: str) -> dict:
    """Compose one AUTHORIZE pledge from the catalogue and the contributor's words."""
    place = _place(message)
    miles = _MILES.search(message or "")
    if miles:
        try:
            count = Decimal(miles.group(1).replace(",", "."))
        except InvalidOperation:
            count = Decimal("1")
        if count <= 0:
            count = Decimal("1")
        amount = (count * MILE_EUR).quantize(Decimal("0.01"))
        label = miles.group(1).replace(",", ".")
        return {
            "amount_eur": f"{amount:.2f}",
            "currency": "EUR",
            "description": f"{label} milles parrainés",
            "milestone_id": place,
            "intent": "AUTHORIZE",
            "item": "mile",
        }
    if _DINNER.search(message or ""):
        return {
            "amount_eur": f"{DINNER_EUR:.2f}",
            "currency": "EUR",
            "description": "Dîner d'escale",
            "milestone_id": place,
            "intent": "AUTHORIZE",
            "item": "dinner",
        }
    return {
        "amount_eur": f"{MILE_EUR:.2f}",
        "currency": "EUR",
        "description": "1 mille parrainé",
        "milestone_id": place,
        "intent": "AUTHORIZE",
        "item": "mile",
    }


def _fallback_report(milestone_id: str, decision: str, evidence: dict) -> str:
    source = evidence.get("source") or "simulation"
    provider = evidence.get("provider") or "NAVIGUIDE"
    flag = evidence.get("flag") or "simulation"
    return (
        f"Jalon {milestone_id} : preuve {provider} marquée {flag} "
        f"(source {source}). Proposition : {decision}. "
        "Le capitaine ne capture ni n'annule ; seul le trésorier peut le faire."
    )


def _fallback_chat(suggested: dict, url: str) -> str:
    text = (
        "Promesse suggérée, sans débit : "
        f"{suggested['description']} ({suggested['amount_eur']} EUR), "
        f"jalon {suggested['milestone_id']}, autorisation seulement."
    )
    if url:
        return f"{text} Pour l'adhésion, le lien HelloAsso est {url}."
    return f"{text} Pour l'adhésion, le lien HelloAsso n'est pas configuré."


async def _llm_text(prompt: str, system: str) -> Optional[str]:
    """BI LLM when one is configured. Any failure returns None so the fallback is used."""
    try:
        from app.core import llm
    except Exception:
        return None
    try:
        if not llm.has_llm():
            return None
    except Exception:
        return None
    try:
        text = await llm.ask_text(prompt, system=system, max_tokens=500)
    except Exception:
        return None
    text = (text or "").strip()
    return text or None


def _read(reader: Optional[ReadOnlyTools], pledge: dict) -> None:
    if reader is None:
        return
    order_id = pledge.get("order_id")
    if order_id:
        try:
            reader.get("orders.get", order_id)
        except PermissionError:
            raise
        except Exception:
            pass
    authorization_id = pledge.get("authorization_id")
    if authorization_id:
        try:
            reader.get("authorizations.get", authorization_id)
        except PermissionError:
            raise
        except Exception:
            pass


async def review(milestone_id: str, reader: Optional[ReadOnlyTools] = None) -> dict:
    """Propose capture or void from evidence. Does not execute either."""
    milestone = await get_milestone(milestone_id)
    evidence = latest_trusted_evidence(milestone)
    decision = decision_for(evidence.get("met") if evidence else None)
    related = await pledges_for_milestone(milestone_id)
    concerned = [
        pledge
        for pledge in related
        if pledge.get("status") in ("authorized", "vaulted")
    ]
    for pledge in concerned:
        _read(reader, pledge)
    allowed = {
        "evidence": evidence,
        "milestone_id": milestone_id,
        "decision": decision,
    }
    prompt = json.dumps(allowed, ensure_ascii=False, default=str)
    narrative = await _llm_text(prompt, _REPORT_SYSTEM)
    if not narrative:
        narrative = _fallback_report(milestone_id, decision, evidence)
    narrative = filter_numbers(narrative, allowed)
    justification = filter_numbers(f"{narrative} Décision : {decision}.", allowed)
    proposal = {
        "milestone_id": milestone_id,
        "proposal": decision,
        "report": narrative,
        "justification": justification,
        "pledge_ids": [pledge["_id"] for pledge in concerned],
        "evidence_flag": evidence.get("flag"),
        "at": now_iso(),
    }
    from .provisioning_channel3 import attach_provisioning

    proposal = attach_provisioning(proposal, milestone_id)
    await get_ledger().set_proposal(milestone_id, proposal)
    from .audit import record
    await record(
        "proposal",
        actor="captain",
        milestone_id=milestone_id,
        proposal=decision,
        justification=justification,
        pledge_ids=proposal["pledge_ids"],
    )
    return proposal


async def chat(message: str) -> dict:
    """Help a contributor phrase a pledge and offer the HelloAsso membership URL."""
    text = (message or "").strip()
    if not text:
        raise ValueError("message is required")
    suggested = suggest_pledge(text)
    url = membership_url()
    allowed = {"message": text, "suggested": suggested, "membership_url": url}
    prompt = json.dumps(allowed, ensure_ascii=False, default=str)
    raw = await _llm_text(prompt, _CHAT_SYSTEM)
    if not raw:
        raw = _fallback_chat(suggested, url)
    elif url and url not in raw:
        raw = f"{raw} Pour l'adhésion, le lien HelloAsso est {url}."
    reply = filter_numbers(raw, allowed)
    return {
        "reply": reply,
        "membership_url": url,
        "suggested_pledge": suggested,
    }
