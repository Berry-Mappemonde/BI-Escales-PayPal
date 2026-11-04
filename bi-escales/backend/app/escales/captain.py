"""Captain: composes a pledge in chat and proposes capture or void.

This module never imports the PayPal client. It cannot capture or void.
A proposal is a recommendation for the treasurer, written to escales_audit.
Prices come from the catalogue below, not from the model.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from .config import AUTH_MAX_DAYS, membership_url
from .milestones import (
    amount_in_text,
    decision_for,
    filter_numbers,
    format_amount,
    get_milestone,
    latest_evidence,
)
from .pledges import get_ledger, now_iso, pledges_for_milestone
from .toolkit_tools import ReadOnlyTools

# Bureau prices. The model is not allowed to invent another tariff.
MILE_EUR = Decimal("1.00")
DINNER_EUR = Decimal("60.00")

_MILES = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:nautical\s+|nautiques?\s+)?(?:milles?|miles?|nm|mi)\b",
    re.IGNORECASE,
)
_DINNER = re.compile(r"\bd[iî]ners?\b|\bdinners?\b", re.IGNORECASE)
_PLACE = re.compile(
    r"(?:près de|pres de|près d'|pres d'|near)\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ-]{1,40})",
    re.IGNORECASE,
)

# Per-call temperatures. NIM_TEMPERATURE, when set, still wins inside the NIM call.
_REPORT_TEMPERATURE = 0.2
_CHAT_TEMPERATURE = 0.3
_CHAT_WORD_LIMIT = 80

_EN_HINT = re.compile(
    r"\b(?:i|i'd|i’m|i'm|would|like|sponsor|please|the|near|miles?|nautical|dinner|and"
    r"|my|you|your|will|is|are|was|old|days?|authorization|it|this)\b",
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
_STATUS_Q = re.compile(
    r"\b(?:statuts?|status|états?|etats?)\b"
    r"|où en est|ou en est|où en sommes|ou en sommes",
    re.IGNORECASE,
)
# A stated authorization age, not an unrelated count in the same sentence.
_AUTH_AGE = re.compile(
    r"(\d+)\s*[- ]?\s*(?:day|days|jour|jours)[- ]?\s*(?:old\s+)?"
    r"(?:authorization|authorisation|autorisation)"
    r"|(?:authorization|authorisation|autorisation)\D{0,40}?"
    r"(\d+)\s*[- ]?\s*(?:day|days|jour|jours)",
    re.IGNORECASE,
)
_EXPIRED_CLAIM = re.compile(
    r"expir(?:e(?:s|d)?|ing|era(?:it)?|é(?:e|s|es)?)"
    r"|has expired|a expir|périm\w*|perim\w*|échue?s?|echue?s?"
    r"|no longer valid|plus valide|n['’]est plus valide|lapsed"
    r"|honor\s*period|p[ée]riode d['’]honneur",
    re.IGNORECASE,
)
_STILL_VALID_REASON = "authorization still valid: younger than 29 days"
# Either order: "Captain Blue Intelligence" or "Blue Intelligence Escales Captain".
_ROLE = r"(?:the\s+|le\s+)?(?:captain|capitaine)"
_BLUE = r"blue\s+intelligence(?:\s+escales)?"
_LONG_SIGNATURE = re.compile(
    rf"(?:[—–\-]\s*)?(?:"
    rf"{_ROLE}\s+(?:de\s+la\s+|of\s+(?:the\s+)?)?{_BLUE}"
    rf"|{_BLUE}\s+{_ROLE}"
    rf")",
    re.IGNORECASE,
)
_URL_RE = re.compile(
    r"https?://[^\s<>\"']+|www\.[^\s<>\"']+|/[^\s<>\"']*adh[ée]sions?/[^\s<>\"']+",
    re.IGNORECASE,
)
_MEMBERSHIP_WORD = re.compile(
    r"helloasso|adh[ée]sions?|membership|adhesion-\[",
    re.IGNORECASE,
)
_AWAY_CLAIM = re.compile(
    r"\baway\b|\bremaining\b|\brestant(?:e|s|es)?\b"
    r"|\bmiles?\s+away\b|\bmilles?\s+loin\b|\bà parcourir\b|\bdistance restante\b",
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


def _is_status_question(message: str) -> bool:
    return bool(_STATUS_Q.search(message or ""))


def _no_pledge_suggestion(message: str) -> bool:
    """Treasurer and status questions are not a pledge to price."""
    return _is_treasurer_question(message) or _is_status_question(message)


def _report_system(milestone_id: str, reached: bool = False) -> str:
    text = (
        "You are the Blue Intelligence Escales captain. "
        "Write exactly 2 or 3 sentences. No title, no heading, no list. "
        f"Keep this leg name verbatim: {milestone_id}. "
        "Use only numbers present in the evidence JSON. Do not invent a figure. "
        "The decision field is fixed by the program. "
        "Anything you write is advisory and is not executed."
    )
    if reached:
        text += (
            " This leg was reached. There is no remaining distance."
            " Do not say the leg is away, or that any distance is left."
        )
    return text


def _chat_system(lang: str) -> str:
    language = "English" if lang == "en" else "French"
    return (
        f"You are the Blue Intelligence Escales captain. Reply in {language}. "
        "Repeat the computed pledge exactly: amount, currency, description, milestone and intent. "
        "Do not propose to take or release money. Do not create an order. Do not invent a price. "
        "If the message asks whether money will be taken or released, say that only the treasurer review decides. "
        "Mention membership only by repeating the HelloAsso URL you were given. "
        "If no URL was given, do not mention membership and do not write any URL. "
        "Sign once, and do not repeat your name. At most 80 words."
    )


def _place(message: str) -> str:
    match = _PLACE.search(message or "")
    if not match:
        return "unspecified"
    slug = re.sub(r"[^a-z0-9]+", "-", match.group(1).lower()).strip("-")
    return slug or "unspecified"


def _format_count(count: Decimal) -> str:
    integral = count.to_integral_value()
    if count == integral:
        return str(int(integral))
    return f"{count.quantize(Decimal('0.01')):.2f}".rstrip("0").rstrip(".")


def _miles_description(count: Decimal, lang: str) -> str:
    label = _format_count(count)
    if lang == "en":
        noun = "sponsored mile" if count == 1 else "sponsored miles"
        return f"{label} {noun}"
    if count == 1:
        return "1 mille parrainé"
    return f"{label} milles parrainés"


def _dinner_description(count: int, lang: str) -> str:
    if lang == "en":
        return "port dinner" if count == 1 else f"{count} port dinners"
    return "Dîner d'escale" if count == 1 else f"{count} dîners d'escale"


def _pledge_description(total_miles: Decimal, dinners: int, lang: str) -> str:
    parts: list[str] = []
    if total_miles > 0:
        parts.append(_miles_description(total_miles, lang))
    if dinners > 0:
        parts.append(_dinner_description(dinners, lang))
    if not parts:
        parts.append(_miles_description(Decimal("1"), lang))
    if lang == "en":
        return " and ".join(parts)
    if len(parts) == 2:
        dinner = parts[1][0].lower() + parts[1][1:]
        return f"{parts[0]} et {dinner}"
    return parts[0]


def suggest_pledge(message: str, lang: str = "fr") -> Optional[dict]:
    """Compose one AUTHORIZE pledge from every catalogue item in the message.

    Miles are 1.00 EUR each and a dinner is 60.00 EUR. Both in the same
    message are added. Treasurer and status questions get no suggestion.
    The description follows ``lang``: ``120 sponsored miles`` in English,
    ``milles parrainés`` only in French.
    """
    if _no_pledge_suggestion(message):
        return None
    text = message or ""
    place = _place(text)
    counts: list[Decimal] = []
    for match in _MILES.finditer(text):
        try:
            count = Decimal(match.group(1).replace(",", "."))
        except InvalidOperation:
            continue
        if count > 0:
            counts.append(count)
    dinners = len(_DINNER.findall(text))
    if not counts and dinners == 0:
        counts = [Decimal("1")]
    total_miles = sum(counts, Decimal("0"))
    amount = (total_miles * MILE_EUR + DINNER_EUR * dinners).quantize(Decimal("0.01"))
    if total_miles > 0 and dinners:
        item = "mixed"
    elif dinners:
        item = "dinner"
    else:
        item = "mile"
    return {
        "amount_eur": f"{amount:.2f}",
        "currency": "EUR",
        "description": _pledge_description(total_miles, dinners, lang),
        "milestone_id": place,
        "intent": "AUTHORIZE",
        "item": item,
    }


def _fallback_report(milestone_id: str, decision: str, evidence: dict, lang: str = "fr") -> str:
    source = evidence.get("source") or "simulation"
    provider = evidence.get("provider") or "NAVIGUIDE"
    flag = evidence.get("flag") or "simulation"
    if lang == "en":
        return (
            f"Milestone {milestone_id}: {provider} evidence marked {flag} "
            f"(source {source}). Proposal: {decision}. "
            "The captain does not capture or void; only the treasurer can."
        )
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
    """Drop every model sign-off so the reply can add exactly one."""
    cleaned = _LONG_SIGNATURE.sub(" ", text or "")
    cleaned = re.sub(
        r"[—–\-]+\s*(?:le capitaine|the captain)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"(?:[—–\-]+\s*)?(?:le capitaine|the captain)\s*$",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s{2,}", " ", cleaned).strip(" \t—–-")


def _currency_present(text: str, currency: str) -> bool:
    folded = (text or "").casefold()
    code = str(currency or "").casefold()
    if code and code in folded:
        return True
    return code == "eur" and "€" in (text or "")


def _pledge_line(suggested: dict, lang: str) -> str:
    shown = format_amount(suggested.get("amount_eur"), lang)
    exact = (
        f"{suggested['description']} ({shown}), "
        f"{suggested['milestone_id']}, {suggested['intent']}"
    )
    if lang == "en":
        return f"Computed pledge, no charge: {exact}."
    return f"Promesse calculée, sans débit : {exact}."


def _has_exact_pledge(text: str, suggested: dict) -> bool:
    """True when the model already stated the computed pledge, in any spelling."""
    folded = (text or "").casefold()
    description = str(suggested.get("description") or "").casefold()
    milestone = str(suggested.get("milestone_id") or "").casefold()
    intent = str(suggested.get("intent") or "").casefold()
    currency = str(suggested.get("currency") or "").casefold()
    if not (description and milestone and intent):
        return False
    if description not in folded or milestone not in folded or intent not in folded:
        return False
    if not _currency_present(text or "", currency):
        return False
    return amount_in_text(text or "", str(suggested.get("amount_eur") or ""))


def _membership_line(url: str, lang: str) -> str:
    """The only membership sentence. It exists only when code has a URL."""
    if lang == "en":
        return f"For membership, the HelloAsso link is {url}."
    return f"Pour l'adhésion, le lien HelloAsso est {url}."


def _clean_model_urls(text: str, url: str) -> str:
    """Drop URLs the model invented. Code inserts the configured URL later."""
    allowed = (url or "").strip()

    def replace(match: re.Match) -> str:
        found = match.group(0).rstrip(".,;:)")
        if allowed and found == allowed:
            return found
        return ""

    cleaned = _URL_RE.sub(replace, text or "")
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?…])", r"\1", cleaned)
    kept: list[str] = []
    for sentence in _split_sentences(cleaned):
        body = sentence.strip()
        if not body or re.fullmatch(r"[\s\W_]+", body):
            continue
        mentions = bool(_MEMBERSHIP_WORD.search(body) or re.search(r"https?://|www\.", body, re.I))
        if allowed:
            if mentions and allowed not in body:
                continue
        elif mentions:
            continue
        kept.append(body)
    return " ".join(kept).strip()


def _assert_reached(text: str, milestone_id: str, lang: str) -> str:
    """A reached leg has no distance left. Drop a sentence that says otherwise."""
    kept = [sentence for sentence in _split_sentences(text) if not _AWAY_CLAIM.search(sentence)]
    if lang == "en":
        fact = f"Milestone {milestone_id} was reached, with no remaining distance."
    else:
        fact = f"L'escale {milestone_id} est atteinte, sans distance restante."
    if not any(re.search(r"no remaining distance|sans distance restante", sentence, re.I) for sentence in kept):
        kept.append(fact)
    if len(kept) < 2:
        kept.append(f"{_leg_word(lang)} {milestone_id}.")
    if len(kept) > 3:
        kept = kept[:-1][:2] + kept[-1:]
    return " ".join(kept)


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
    suggested: Optional[dict],
    url: str,
    lang: str,
    *,
    treasurer: bool,
) -> str:
    """Pledge repeated exactly, one signature, at most 80 words."""
    if treasurer or not suggested:
        if treasurer:
            if lang == "en":
                prose = "This question belongs to the treasurer review. The captain does not decide it."
            else:
                prose = "Cette question relève de la revue du trésorier. Le capitaine ne la tranche pas."
        elif lang == "en":
            prose = "This question is about status. The captain does not suggest a pledge."
        else:
            prose = "Cette question porte sur le statut. Le capitaine ne propose pas de promesse."
        return _fit_words("", [prose, _signature(lang)])
    prose = _strip_signatures(model_text)
    prose = _clean_model_urls(prose, url)
    prose = _drop_sentences(prose, _POLICY_RE)
    prose = _drop_sentences(prose, _CHAT_DECIDE_RE)
    required: list[str] = []
    if not _has_exact_pledge(prose, suggested):
        required.append(_pledge_line(suggested, lang))
    joined = " ".join(required)
    if url and url not in prose and url not in joined:
        required.append(_membership_line(url, lang))
    required.append(_signature(lang))
    return _fit_words(prose, required)


def _leg_word(lang: str) -> str:
    return "Milestone" if lang == "en" else "Jalon"


def _without_jalon(text: str, lang: str) -> str:
    """English reports say Milestone. French reports keep Jalon."""
    if lang != "en":
        return text
    return re.sub(r"\bJalons?\b", "Milestone", text or "", flags=re.IGNORECASE)


def _shape_report(text: str, milestone_id: str, lang: str = "fr") -> str:
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
    if lang == "en":
        sentences = [_without_jalon(sentence, "en") for sentence in sentences]
    leg = _leg_word(lang)
    if milestone_id not in " ".join(sentences):
        sentences.append(f"{leg} {milestone_id}.")
    if len(sentences) < 2:
        sentences.append(f"{leg} {milestone_id}.")
    return _without_jalon(" ".join(sentences[:3]), lang)


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


def _parse_iso(raw: Optional[str]) -> Optional[dt.datetime]:
    text = (raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment


def authorization_age_days(
    pledge: dict,
    now: Optional[dt.datetime] = None,
) -> Optional[int]:
    """Whole days since authorization. None when the pledge does not say."""
    raw = pledge.get("authorization_age_days")
    if raw is not None and str(raw).strip() != "":
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    expiry = _parse_iso(pledge.get("authorization_expires_at"))
    if expiry is None:
        return None
    moment = now or dt.datetime.now(dt.timezone.utc)
    authorized = expiry - dt.timedelta(days=AUTH_MAX_DAYS)
    return (moment - authorized).days


def _known_authorization_age(pledges: list[dict]) -> Optional[int]:
    ages = [
        age for age in (authorization_age_days(pledge) for pledge in pledges) if age is not None
    ]
    if not ages:
        return None
    return min(ages)


def _stated_authorization_age(reason: str) -> Optional[int]:
    match = _AUTH_AGE.search(reason or "")
    if not match:
        return None
    raw = match.group(1) or match.group(2)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def validate_advisory_proposal(
    proposal: Optional[str],
    reason: Optional[str],
    age_days: Optional[int] = None,
    met: Optional[bool] = None,
) -> dict:
    """Check an ask_json proposal against the code decision and the 29-day rule.

    ``decision_for(met)`` is the only action the model may repeat. A different
    proposal is dropped and flagged contradicted. An authorization younger
    than 29 days is still valid, so a reason that claims it has expired, or
    that it expires in one day, is overridden.
    The result is always advisory: it never replaces the code decision.
    """
    raw_proposal = (proposal or "").strip().lower() or None
    raw_reason = (reason or "").strip() or None
    known = age_days
    stated = _stated_authorization_age(raw_reason or "")
    age = known if known is not None else stated
    still_valid = None if age is None else age < AUTH_MAX_DAYS
    code_decision = decision_for(met)
    reason_contradicts = bool(still_valid and raw_reason and _EXPIRED_CLAIM.search(raw_reason))
    proposal_differs = bool(raw_proposal) and raw_proposal != code_decision
    proposal_contradicts = proposal_differs
    if still_valid and raw_proposal == "reauthorize":
        proposal_contradicts = True
    if still_valid and raw_proposal == "void" and reason_contradicts:
        proposal_contradicts = True
    contradicted = proposal_contradicts or reason_contradicts
    shown_reason = _STILL_VALID_REASON if reason_contradicts else raw_reason
    shown_proposal = None if proposal_contradicts else raw_proposal
    return {
        "advisory": True,
        "label": "advisory",
        "proposal": shown_proposal,
        "reason": shown_reason,
        "raw_proposal": raw_proposal,
        "raw_reason": raw_reason,
        "dropped": contradicted,
        "contradicted": contradicted,
        "code_decision": code_decision,
        "authorization_age_days": age,
        "authorization_valid": still_valid,
    }


async def _advisory_proposal(allowed: dict, age: Optional[int]) -> Optional[dict]:
    """ask_json opinion, validated. Failure leaves the code decision alone."""
    try:
        from app.core import llm
    except Exception:
        return None
    try:
        if not llm.has_llm():
            return None
    except Exception:
        return None
    payload = dict(allowed)
    payload["authorization_age_days"] = age
    prompt = json.dumps(payload, ensure_ascii=False, default=str)
    try:
        parsed = await llm.ask_json(prompt, max_tokens=180, temperature=0)
    except Exception:
        return None
    data = parsed.data if isinstance(getattr(parsed, "data", None), dict) else {}
    evidence = allowed.get("evidence") if isinstance(allowed, dict) else None
    met = evidence.get("met") if isinstance(evidence, dict) else None
    checked = validate_advisory_proposal(
        str(data.get("proposal") or ""),
        str(data.get("reason") or ""),
        age,
        met=met if isinstance(met, bool) else None,
    )
    checked["provider"] = getattr(parsed, "provider", "") or ""
    checked["model"] = getattr(parsed, "model", "") or ""
    return checked


async def review(milestone_id: str, reader: Optional[ReadOnlyTools] = None) -> dict:
    """Propose capture or void from evidence. Does not execute either."""
    milestone = await get_milestone(milestone_id)
    evidence = latest_evidence(milestone)
    met = evidence.get("met") if evidence else None
    reached = met is True
    decision = decision_for(met if isinstance(met, bool) else None)
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
        _report_system(milestone_id, reached=reached),
        max_tokens=220,
        temperature=_REPORT_TEMPERATURE,
    )
    if not narrative:
        narrative = _fallback_report(milestone_id, decision, evidence, lang="fr")
        source = _rules_source()
        report_lang = "fr"
    else:
        report_lang = message_lang(narrative)
        narrative = _shape_report(narrative, milestone_id, report_lang)
    if reached:
        narrative = _assert_reached(narrative, milestone_id, report_lang)
    narrative = _without_jalon(filter_numbers(narrative, allowed, lang=report_lang), report_lang)
    decision_line = (
        f" Decision: {decision}." if report_lang == "en" else f" Décision : {decision}."
    )
    justification = _without_jalon(
        filter_numbers(f"{narrative}{decision_line}", allowed, lang=report_lang),
        report_lang,
    )
    age = _known_authorization_age(concerned)
    advisory = await _advisory_proposal(allowed, age)
    proposal = {
        "milestone_id": milestone_id,
        "proposal": decision,
        "report": narrative,
        "justification": justification,
        "pledge_ids": [pledge["_id"] for pledge in concerned],
        "evidence_flag": evidence.get("flag"),
        "model_source": source,
        "llm_proposal": advisory,
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
    url = membership_url()
    lang = message_lang(text)
    treasurer = _is_treasurer_question(text)
    suggested = suggest_pledge(text, lang)
    allowed = {"message": text, "suggested": suggested, "membership_url": url}
    if treasurer or suggested is None:
        # Do not send this question to a model: the horizon rule stays in code.
        raw, source = "", _rules_source()
    else:
        prompt = json.dumps(allowed, ensure_ascii=False, default=str)
        raw, source = await _llm_text(
            prompt, _chat_system(lang), max_tokens=220, temperature=_CHAT_TEMPERATURE,
        )
        if raw:
            raw = filter_numbers(raw, allowed, lang=lang)
        else:
            raw, source = "", _rules_source()
    reply = _compose_chat_reply(raw or "", suggested, url, lang, treasurer=treasurer)
    return {
        "reply": reply,
        "membership_url": url,
        "suggested_pledge": suggested,
        "model_source": source,
    }
