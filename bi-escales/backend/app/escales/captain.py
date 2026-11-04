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

_MILES = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:nautical\s+|nautiques?\s+)?(?:milles?|miles?|nm)\b",
    re.IGNORECASE,
)
_DINNER = re.compile(r"d[iî]ners?|dinner", re.IGNORECASE)
_PLACE = re.compile(
    r"(?:près de|pres de|près d'|pres d'|near)\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ-]{1,40})",
    re.IGNORECASE,
)

# Reports ask for about 0.2. NIM_TEMPERATURE, when set, still wins inside the NIM call.
_REPORT_TEMPERATURE = 0.2
_CHAT_WORD_LIMIT = 80

_EN_HINT = re.compile(
    r"\b(?:i|i'd|i’m|i'm|would|like|sponsor|please|the|near|miles?|nautical|dinner|and)\b",
    re.IGNORECASE,
)
_FR_HINT = re.compile(
    r"\b(?:je|j'|voudrais|parrain\w*|milles?|près|pres|pour|dîner|diner|une|des|autorisation|est-ce)\b",
    re.IGNORECASE,
)
_TREASURER_Q = re.compile(
    r"encaiss|annul|captur|void|tr[ée]sorier|treasurer|authori[sz]ation|autorisation",
    re.IGNORECASE,
)
# Horizon and re-issue policy stay in code. Drop them if a model writes them anyway.
_POLICY_RE = re.compile(
    r"\b29\s*(?:jours|days|day)\b"
    r"|honor\s*period"
    r"|p[ée]riode d['’]honneur"
    r"|re-?authori\w*"
    r"|r[ée]autoris\w*",
    re.IGNORECASE,
)
_CHAT_DECIDE_RE = re.compile(
    r"\b(?:je propose|i propose|we propose|nous proposons|proposition\s*:)\b"
    r"|\b(?:will capture|will void|vais encaisser|vais annuler)\b"
    r"|\bcapture\b|\bvoid\b|\bencaiss\w*|\bannul\w*",
    re.IGNORECASE,
)


def message_lang(text: str) -> str:
    """Language of the contributor message. French when the signals tie."""
    en = len(_EN_HINT.findall(text or ""))
    fr = len(_FR_HINT.findall(text or ""))
    if en > fr:
        return "en"
    return "fr"


def _is_treasurer_question(message: str) -> bool:
    return bool(_TREASURER_Q.search(message or ""))


def _report_system(milestone_id: str) -> str:
    return (
        "You are the Blue Intelligence Escales captain. "
        "Write exactly 2 or 3 sentences. No title, no heading, no list. "
        f"Keep this leg name verbatim: {milestone_id}. "
        "Use only numbers present in the evidence JSON. Do not invent a figure. "
        "The decision word in the JSON is only a proposal for the treasurer. "
        "You do not execute it."
    )


def _chat_system(lang: str) -> str:
    language = "English" if lang == "en" else "French"
    return (
        f"You are the Blue Intelligence Escales captain. Reply in {language}. "
        "Repeat the computed pledge exactly: amount, currency, description, milestone and intent. "
        "Do not propose to take or release money. Do not create an order. Do not invent a price. "
        "If the message asks whether money will be taken or released, say that only the treasurer review decides. "
        "Mention membership only with the HelloAsso URL you were given. "
        "Sign once. At most 80 words."
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


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+", (text or "").strip())
    return [part.strip() for part in parts if part.strip()]


def _drop_sentences(text: str, pattern: re.Pattern) -> str:
    kept = [sentence for sentence in _split_sentences(text) if not pattern.search(sentence)]
    return " ".join(kept).strip()


def _signature(lang: str) -> str:
    return "— The captain" if lang == "en" else "— Le capitaine"


def _strip_signatures(text: str) -> str:
    return re.sub(
        r"[—–-]{1,2}\s*(?:Le capitaine|The captain)\b",
        "",
        text or "",
        flags=re.IGNORECASE,
    ).strip()


def _pledge_line(suggested: dict, lang: str) -> str:
    exact = (
        f"{suggested['description']} ({suggested['amount_eur']} {suggested['currency']}), "
        f"{suggested['milestone_id']}, {suggested['intent']}"
    )
    if lang == "en":
        return f"Computed pledge, no charge: {exact}."
    return f"Promesse calculée, sans débit : {exact}."


def _has_exact_pledge(text: str, suggested: dict) -> bool:
    return all(
        str(suggested[key]) in (text or "")
        for key in ("description", "amount_eur", "currency", "milestone_id", "intent")
    )


def _membership_line(url: str, lang: str) -> str:
    if url:
        if lang == "en":
            return f"For membership, the HelloAsso link is {url}."
        return f"Pour l'adhésion, le lien HelloAsso est {url}."
    if lang == "en":
        return "The HelloAsso membership link is not configured."
    return "Pour l'adhésion, le lien HelloAsso n'est pas configuré."


def _word_count(text: str) -> int:
    return len((text or "").split())


def _fit_words(prose: str, required: list[str], limit: int = _CHAT_WORD_LIMIT) -> str:
    prose = (prose or "").strip()
    tail = [part.strip() for part in required if part and part.strip()]
    tail_text = " ".join(tail)
    while prose and _word_count(f"{prose} {tail_text}".strip()) > limit:
        words = prose.split()
        if len(words) <= 1:
            prose = ""
            break
        prose = " ".join(words[:-1]).rstrip(" ,;:")
    parts = [prose] if prose else []
    parts.extend(tail)
    return " ".join(parts).strip()


def _compose_chat_reply(
    model_text: str,
    suggested: dict,
    url: str,
    lang: str,
    *,
    treasurer: bool,
) -> str:
    """Pledge repeated exactly, one signature, at most 80 words."""
    if treasurer:
        if lang == "en":
            prose = "This question belongs to the treasurer review. The captain does not decide it."
        else:
            prose = "Cette question relève de la revue du trésorier. Le capitaine ne la tranche pas."
        return _fit_words("", [prose, _signature(lang)])
    prose = _strip_signatures(model_text)
    prose = _drop_sentences(prose, _POLICY_RE)
    prose = _drop_sentences(prose, _CHAT_DECIDE_RE)
    required: list[str] = []
    if not _has_exact_pledge(prose, suggested):
        required.append(_pledge_line(suggested, lang))
    joined = " ".join(required)
    if url and url not in prose and url not in joined:
        required.append(_membership_line(url, lang))
    elif not url and "HelloAsso" not in prose and "HelloAsso" not in joined:
        required.append(_membership_line("", lang))
    required.append(_signature(lang))
    return _fit_words(prose, required)


def _shape_report(text: str, milestone_id: str) -> str:
    """Two or three sentences, no title, leg name kept verbatim."""
    lines = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if line.startswith("#"):
            line = line.lstrip("#").strip()
            if not line or (len(line) < 80 and not re.search(r"[.!?…]$", line)):
                continue
        if line:
            lines.append(line)
    punctuated = [line for line in lines if re.search(r"[.!?…]$", line)]
    if punctuated:
        lines = [line for line in lines if re.search(r"[.!?…]$", line) or len(line) >= 80]
    body = " ".join(lines).strip()
    if body and not re.search(r"[.!?…]$", body):
        body += "."
    sentences = [
        sentence.strip()
        for sentence in _split_sentences(body)
        if sentence.strip() and not _POLICY_RE.search(sentence)
    ]
    if milestone_id not in " ".join(sentences):
        sentences.append(f"Jalon {milestone_id}.")
    if len(sentences) < 2:
        sentences.append(f"Jalon {milestone_id}.")
    return " ".join(sentences[:3])


def _rules_source() -> dict[str, str]:
    return {"provider": "rules", "model": ""}


def _text_of(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    return str(getattr(raw, "text", "") or "").strip()


def _source_of(raw: Any, text: str) -> dict[str, str]:
    """Provider and model from the cascade. A bare string has no model id."""
    provider = getattr(raw, "provider", None)
    model = getattr(raw, "model", None)
    if isinstance(provider, str) and provider.strip():
        return {"provider": provider.strip(), "model": str(model or "").strip()}
    if text:
        return {"provider": "llm", "model": ""}
    return _rules_source()


async def _llm_text(
    prompt: str,
    system: str,
    *,
    max_tokens: int = 220,
    temperature: Optional[float] = None,
) -> tuple[Optional[str], dict[str, str]]:
    """BI LLM when one is configured. Any failure returns no text so the rules apply."""
    try:
        from app.core import llm
    except Exception:
        return None, _rules_source()
    try:
        if not llm.has_llm():
            return None, _rules_source()
    except Exception:
        return None, _rules_source()
    try:
        raw = await llm.ask_text(
            prompt, system=system, max_tokens=max_tokens, temperature=temperature,
        )
    except Exception:
        return None, _rules_source()
    text = _text_of(raw)
    if not text:
        return None, _rules_source()
    return text, _source_of(raw, text)


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
    narrative, source = await _llm_text(
        prompt,
        _report_system(milestone_id),
        max_tokens=220,
        temperature=_REPORT_TEMPERATURE,
    )
    if not narrative:
        narrative = _fallback_report(milestone_id, decision, evidence)
        source = _rules_source()
    else:
        narrative = _shape_report(narrative, milestone_id)
    narrative = filter_numbers(narrative, allowed)
    justification = filter_numbers(f"{narrative} Décision : {decision}.", allowed)
    proposal = {
        "milestone_id": milestone_id,
        "proposal": decision,
        "report": narrative,
        "justification": justification,
        "pledge_ids": [pledge["_id"] for pledge in concerned],
        "evidence_flag": evidence.get("flag"),
        "model_source": source,
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
    lang = message_lang(text)
    treasurer = _is_treasurer_question(text)
    allowed = {"message": text, "suggested": suggested, "membership_url": url}
    if treasurer:
        # Do not send this question to a model: the horizon rule stays in code.
        raw, source = "", _rules_source()
    else:
        prompt = json.dumps(allowed, ensure_ascii=False, default=str)
        raw, source = await _llm_text(prompt, _chat_system(lang), max_tokens=220)
        if raw:
            raw = filter_numbers(raw, allowed)
        else:
            raw, source = "", _rules_source()
    reply = _compose_chat_reply(raw or "", suggested, url, lang, treasurer=treasurer)
    return {
        "reply": reply,
        "membership_url": url,
        "suggested_pledge": suggested,
        "model_source": source,
    }
