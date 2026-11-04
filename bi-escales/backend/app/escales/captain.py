"""Captain: composes a pledge in chat and proposes capture or void.

This module never imports the PayPal client. It cannot capture or void.
A proposal is a recommendation for the treasurer, written to escales_audit.
Prices come from the catalogue below, not from the model.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import time
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
from .pledges import PLEDGE_KINDS, get_ledger, now_iso, pledges_for_milestone
from .toolkit_tools import ReadOnlyTools

log = logging.getLogger("escales.captain")

# Bureau prices. The model is not allowed to invent another tariff.
# mile and meal keep these two figures. The other fixed lines are the
# labelled simulation (berth 30, night 60, care 40, cabin leg 80).
# A project pledge and the common fund have no unit: the visitor chooses.
MILE_EUR = Decimal("1.00")
DINNER_EUR = Decimal("60.00")
SIMULATED_PRICE_LABEL = "simulated price"
_SIMULATED_EUR = {
    "mile": MILE_EUR,
    "berth": Decimal("30.00"),
    "night": Decimal("60.00"),
    "meal": DINNER_EUR,
    "care": Decimal("40.00"),
    "cabin_leg": Decimal("80.00"),
}

_MILES = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:nautical\s+|nautiques?\s+)?(?:milles?|miles?|nm|mi)\b",
    re.IGNORECASE,
)
_DINNER = re.compile(r"\bd[iî]ners?\b|\bdinners?\b", re.IGNORECASE)
_PLACE = re.compile(
    r"(?:près de|pres de|près d['’]|pres d['’]|near)\s+"
    r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’ \-]{0,60})",
    re.IGNORECASE,
)

# Per-call temperatures. NIM_TEMPERATURE, when set, still wins inside the NIM call.
_REPORT_TEMPERATURE = 0.2
_CHAT_TEMPERATURE = 0.3
_CHAT_WORD_LIMIT = 80
# Room for two finished sentences. A short budget cuts the model off mid-phrase.
_REPORT_MAX_TOKENS = 400
_CHAT_MAX_TOKENS = 400

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
# A model sentence that restates arrival, completion, or a distance still to sail.
_MILES_AWAY = re.compile(
    r"à\s+\d+(?:[.,]\d+)?\s+milles?"
    r"|\d+(?:[.,]\d+)?\s+(?:nautical\s+)?miles?\s+away",
    re.IGNORECASE,
)
# A real date or clock. The bare word "arrival" is not one.
_HAS_DATE = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"|\b\d{1,2}:\d{2}\b"
    r"|\b\d{1,2}(?:er)?\s+(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|"
    r"septembre|octobre|novembre|d[ée]cembre|january|february|march|april|may|june|"
    r"july|august|september|october|november|december)\b",
    re.IGNORECASE,
)
_REACHED_CLAIM = re.compile(
    r"\breach(?:ed)?\b"
    r"|\batteinte?s?\b"
    r"|no distance|distance remains|aucune distance|plus de distance"
    r"|\bcomplete[ds]?\b|\bcompleted\b"
    r"|\bterminés?\b|\bterminées?\b"
    r"|recorded on"
    r"|enregistr\w*\s+le",
    re.IGNORECASE,
)
_MILES_FROM = re.compile(
    r"\bremains\s+\d+(?:[.,]\d+)?(?:\s+\w+){0,6}\s+miles?\b"
    r"|\b\d+(?:[.,]\d+)?\s+(?:nautical\s+)?miles?\s+from\b"
    r"|\bmilles?\s+nautiques?\s+à\s+\w+"
    r"|\bparcouru\b[^.]{0,48}\bà\s+\w+",
    re.IGNORECASE,
)
_INVENTED_SIGNATURE = re.compile(
    r"capitaine de l['’]escales?\s+bleue"
    r"|je m['’]appelle\s+blue\s+intelligence(?:\s+escales)?"
    r"|\bsignés?\s*,\s*\.?"
    r"|\bsigned\s*,\s*\.?",
    re.IGNORECASE,
)
# Whole sentences. The code adds its own signature afterwards.
_INVENTED_SENTENCE = re.compile(
    r"capitaine\s+des?\s+escales"
    r"|escales\s+bleues?"
    r"|je suis le capitaine"
    r"|je m['’]appelle",
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


# Reports use a wider lexicon than chat. A tie in message_lang is French,
# which appended a French sentence onto English reports that avoid "the" and "is".
_EN_REPORT = re.compile(
    r"\b(?:the|this|that|is|are|was|were|with|and|from|for|not|only|"
    r"reached|milestone|evidence|proposal|treasurer|capture|void|wait|"
    r"away|distance|arrival|recorded|flag|stands|marked|supports|"
    r"complete|boat|funds|released|"
    r"reports|shows|covered|nautical|miles|at|of|vessel|source|simulation)\b",
    re.IGNORECASE,
)
_FR_REPORT = re.compile(
    r"\b(?:le|la|les|un|une|des|du|est|sont|cette|avec|pour|dans|"
    r"atteinte?|jalon|preuve|proposition|tr[ée]sorier|escale|arriv[ée]e|"
    r"enregistr\w*|marqu[ée]e|consultatif|bateau|fonds|lib[ée]r\w*|"
    r"parcourue|distance|source|vers|pr[ée]vus|navire|route)\b",
    re.IGNORECASE,
)
_ECHO_RE = re.compile(
    r"decision field"
    r"|champ (?:de la |de )?d[ée]cision est fix"
    r"|this advisory is not executed"
    r"|this is advisory"
    r"|advisory only"
    r"|anything you write is advisory"
    r"|n['’]est pas ex[ée]cut"
    r"|est consultatif"
    r"|these instructions"
    r"|ces instructions"
    r"|mention membership only"
    r"|you were given"
    r"|on vous a donn"
    r"|^\s*decision\s*:"
    r"|^\s*d[ée]cision\s*:",
    re.IGNORECASE,
)
_DANGLING_WORD = {
    "the", "a", "an", "of", "to", "for", "and", "or", "but", "with", "from", "by",
    "as", "at", "in", "on", "my", "your", "this", "that", "am", "is", "are", "was",
    "were", "be", "been", "its",
    "le", "la", "les", "un", "une", "de", "du", "des", "et", "ou", "au", "aux",
    "en", "pour", "avec", "dans", "sur", "ce", "cette", "mon", "ma", "mes",
    "je", "tu", "il", "est", "suis", "son", "sa", "ses", "que", "qui",
}


def _is_treasurer_question(message: str) -> bool:
    return bool(_TREASURER_Q.search(message or ""))


def _is_status_question(message: str) -> bool:
    return bool(_STATUS_Q.search(message or ""))


def _no_pledge_suggestion(message: str) -> bool:
    """Treasurer and status questions are not a pledge to price."""
    return _is_treasurer_question(message) or _is_status_question(message)


# Accent fold shared with the schedule slug. Spaces and dashes collapse later.
_ACCENT_FOLD = str.maketrans(
    "àâäáéèêëíìîïóòôöúùûüçñ",
    "aaaaeeeeiiiioooouuuucn",
)
# Canonical spelling. The schedule names overlay this table, so every escale
# id is shown as its name and never as a title-cased ``dep-`` slug.
_CANONICAL_DISPLAY = {
    "lorient": "Lorient",
    "dakar": "Dakar",
    "brest": "Brest",
    "mayotte": "Mayotte",
    "fort-de-france": "Fort-de-France",
    "pointe-a-pitre": "Pointe-à-Pitre",
}


def _fold_token(text: str) -> str:
    return (text or "").casefold().translate(_ACCENT_FOLD)


def _escale_slug(token: str) -> str:
    """``dep-fort-de-france`` and ``Pointe-à-Pitre`` share one hyphenated key."""
    slug = re.sub(r"[^a-z0-9]+", "-", _fold_token(token)).strip("-")
    if slug.startswith("dep-"):
        slug = slug[4:]
    return slug


def _compact(text: str) -> str:
    """Accents, dashes, and spaces removed, for chat matching."""
    return re.sub(r"[^a-z0-9]+", "", _fold_token(text))


def _display_names() -> dict[str, str]:
    """Slug → reader name. Schedule rows cover every exported escale id."""
    table = dict(_CANONICAL_DISPLAY)
    from .naviguide_bridge import local_schedule_export

    for item in local_schedule_export().get("escales") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        for raw in (item.get("slug"), item.get("milestone_id"), item.get("name")):
            slug = _escale_slug(str(raw or ""))
            if slug:
                table[slug] = name
    return table


def display_name(milestone_id: str) -> str:
    """Reader name for an escale id. The ``dep-`` prefix is never shown."""
    raw = (milestone_id or "").strip()
    if not raw:
        return raw
    slug = _escale_slug(raw)
    shown = _display_names().get(slug)
    if shown:
        return shown
    return slug or raw


def simulated_unit(kind: str) -> dict:
    """One catalogue line. ``label`` is always ``simulated price``."""
    row = {
        "kind": kind,
        "currency": "EUR",
        "label": SIMULATED_PRICE_LABEL,
        "simulated": True,
    }
    amount = _SIMULATED_EUR.get(kind)
    if amount is not None:
        row["amount_eur"] = f"{amount:.2f}"
    return row


def simulated_prices() -> dict:
    """One row per pledge kind. Fixed lines carry amount_eur."""
    return {
        "simulated": True,
        "label": SIMULATED_PRICE_LABEL,
        "currency": "EUR",
        "prices": [simulated_unit(kind) for kind in PLEDGE_KINDS],
    }


def _report_system(milestone_id: str, reached: bool = False, lang: str = "fr") -> str:
    """Full instructions written in the report language. Code writes the reached sentence."""
    port = display_name(milestone_id)
    if lang == "en":
        count = "exactly 1 short complete sentence" if reached else "exactly 2 short complete sentences"
        text = (
            "You are the Blue Intelligence Escales captain. "
            "Write in English only. "
            f"Write {count}. "
            "End each sentence with one period. Never stop mid-sentence. "
            "Each sentence is complete and contains a verb. "
            "No title, no heading, no list. "
            f"Keep this port name verbatim: {port}. "
            "Use only numbers present in the evidence JSON. Do not invent a figure. "
            "Do not write any date or time. "
            "distance_nm is the distance covered and planned_nm the planned distance. "
            "Write nautical miles or nm immediately after every distance number. "
            "Do not repeat these instructions and do not write a Decision line."
        )
        if not reached:
            text += f" Say the boat is heading toward {port}, never at {port}."
        if reached:
            text += (
                " The code already writes the sentence saying this leg is reached, with its arrival date. "
                "Do not say it is reached, and do not mention any distance left or remaining. "
                "Describe only the evidence (source, distance covered). "
                "Say nautical miles to the port, never miles from the port."
            )
        return text
    count = "exactement 1 phrase courte et complète" if reached else "exactement 2 phrases courtes et complètes"
    text = (
        "Tu es le capitaine de Blue Intelligence Escales. "
        "Réponds uniquement en français, même si les données JSON sont en anglais. "
        f"Écris {count}. "
        "Termine chaque phrase par un seul point. Ne t'arrête jamais au milieu d'une phrase. "
        "Chaque phrase est complète et contient un verbe. "
        "Pas de titre, pas d'intertitre, pas de liste. "
        f"Garde ce nom de port tel quel : {port}. "
        "Utilise seulement les nombres présents dans le JSON de preuve. N'invente aucun chiffre. "
        "N'écris aucune date ni heure. "
        "distance_nm est la distance parcourue et planned_nm la distance prévue. "
        "Écris milles ou nm juste après chaque nombre de distance. "
        "Ne répète pas ces consignes et n'écris pas de ligne Décision."
    )
    if not reached:
        text += f" Dis « en route vers {port} », jamais « à {port} »."
    if reached:
        text += (
            " Le code écrit déjà la phrase qui dit que cette escale est atteinte, avec sa date d'arrivée. "
            "Ne dis pas qu'elle est atteinte, et ne mentionne aucune distance restante. "
            "Décris seulement la preuve (source, distance parcourue)."
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
        "Write complete sentences and never stop mid-sentence. "
        "Sign once, and do not repeat your name. At most 80 words."
    )


# A distorted spelling maps onto a slug from the display table.


def _edit_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if abs(len(left) - len(right)) > 3:
        return 4
    previous = list(range(len(right) + 1))
    for index, left_char in enumerate(left, start=1):
        current = [index]
        for jndex, right_char in enumerate(right, start=1):
            current.append(min(
                current[-1] + 1,
                previous[jndex] + 1,
                previous[jndex - 1] + (left_char != right_char),
            ))
        previous = current
    return previous[-1]


def _shared_prefix(left: str, right: str) -> int:
    count = 0
    for left_char, right_char in zip(left, right):
        if left_char != right_char:
            break
        count += 1
    return count


def _matches_port(token: str, canonical: str) -> bool:
    """Same initial letter. At most two edits, or three when the stem is shared.

    ``lorien`` is one edit from ``lorient``. ``lorain`` is three, with the
    ``lor`` stem and a one-letter length gap. A 4-letter word such as
    ``best`` is left alone so it does not become ``Brest``.
    """
    if not token or not canonical or token[0] != canonical[0]:
        return False
    if token == canonical:
        return True
    if len(token) < 5:
        return False
    distance = _edit_distance(token, canonical)
    stem = _shared_prefix(token, canonical)
    if distance <= 1 and stem >= 1:
        return True
    if distance == 2 and stem >= 3:
        return True
    return distance <= 3 and stem >= 3 and abs(len(token) - len(canonical)) <= 1


def _canonical_slug(token: str, extra: str = "") -> Optional[str]:
    folded = _escale_slug(token)
    if not folded:
        return None
    pool: list[str] = []
    for name in (*_display_names(), _escale_slug(extra)):
        if name and name not in pool:
            pool.append(name)
    for name in pool:
        if folded == name or _compact(folded) == _compact(name):
            return name
    best: Optional[str] = None
    best_distance = 99
    tied = False
    for name in pool:
        if not _matches_port(folded, name):
            continue
        distance = _edit_distance(folded, name)
        if distance < best_distance:
            best = name
            best_distance = distance
            tied = False
        elif distance == best_distance and name != best:
            tied = True
    if tied:
        return None
    return best


def _resolve_escale(token: str) -> Optional[str]:
    """Known escale inside a phrase, then a close spelling such as lorain."""
    compact = _compact(token)
    if compact:
        best: Optional[str] = None
        best_len = 0
        for slug, shown in _display_names().items():
            for key in (_compact(slug), _compact(shown)):
                if key and key in compact and len(key) > best_len:
                    best = slug
                    best_len = len(key)
        if best:
            return best
    return _canonical_slug(token)


def _place(message: str) -> Optional[str]:
    """Escale named in the message. None when none of the schedule matches.

    Accents, dashes, spaces, and case do not matter: Pointe-à-Pitre,
    pointe a pitre, and POINTEAPITRE are the same stop.
    """
    match = _PLACE.search(message or "")
    if match:
        return _resolve_escale(match.group(1))
    return _resolve_escale(message or "")


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
    if not place:
        return None
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
    suggested = {
        "amount_eur": f"{amount:.2f}",
        "currency": "EUR",
        "description": _pledge_description(total_miles, dinners, lang),
        "milestone_id": place,
        "intent": "AUTHORIZE",
        "item": item,
        "simulated": True,
        "price_label": SIMULATED_PRICE_LABEL,
    }
    if item == "mile":
        suggested["kind"] = "mile"
    elif item == "dinner":
        suggested["kind"] = "meal"
    return suggested


def _covered_miles_sentence(evidence: dict, lang: str = "fr") -> str:
    """One code sentence when Lightning's only line was rejected or empty."""
    if not isinstance(evidence, dict):
        return ""
    facts = evidence.get("facts") if isinstance(evidence.get("facts"), dict) else {}
    raw = facts.get("distance_nm")
    if raw is None:
        return ""
    try:
        number = Decimal(str(raw))
    except InvalidOperation:
        return ""
    if number == number.to_integral_value():
        shown = str(int(number))
    else:
        shown = f"{number.quantize(Decimal('0.01'))}"
    provider = str(evidence.get("provider") or "NAVIGUIDE")
    flag = str(evidence.get("flag") or evidence.get("source") or "simulation")
    if lang == "en":
        return f"The {provider} evidence ({flag}) shows {shown} nautical miles covered."
    return f"La preuve {provider} ({flag}) indique {shown} milles parcourus."


def _fallback_report(milestone_id: str, decision: str, evidence: dict, lang: str = "fr") -> str:
    source = evidence.get("source") or "simulation"
    provider = evidence.get("provider") or "NAVIGUIDE"
    flag = evidence.get("flag") or "simulation"
    port = display_name(milestone_id)
    if lang == "en":
        return (
            f"Milestone {port}: {provider} evidence marked {flag} "
            f"(source {source}). Proposal: {decision}. "
            "The captain does not capture or void; only the treasurer can."
        )
    return (
        f"Jalon {port} : preuve {provider} marquée {flag} "
        f"(source {source}). Proposition : {decision}. "
        "Seul le trésorier décide si l'argent est prélevé ou libéré."
    )


_TREASURER_DECIDES = "Seul le trésorier décide si l'argent est prélevé ou libéré."
_BARE_DISTANCE = re.compile(
    r"\b\d+(?:[.,]\d+)?\b(?!\s*(?:nautical\s+miles?|nm|milles?(?:\s+nautiques?)?)\b)",
    re.IGNORECASE,
)
_DISTANCE_TALK = re.compile(
    r"\b(?:distance|covered|planned|sailed|parcourue|pr[ée]vue|milles?|miles?|nm)\b",
    re.IGNORECASE,
)
_MODEL_PLEDGE_LINE = re.compile(r"promesse calculée|computed pledge", re.IGNORECASE)
_STANDALONE_INTENT = re.compile(r"^intent\s*:?\s*authorize\.?$", re.IGNORECASE)


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+", (text or "").strip())
    return [part.strip() for part in parts if part.strip()]


def _distance_without_unit(sentence: str) -> bool:
    """A distance figure with no nautical miles, nm, or milles after it."""
    if not _DISTANCE_TALK.search(sentence or ""):
        return False
    return bool(_BARE_DISTANCE.search(sentence or ""))


def _drop_sentences(text: str, pattern: re.Pattern) -> str:
    kept = [sentence for sentence in _split_sentences(text) if not pattern.search(sentence)]
    return " ".join(kept).strip()


def _report_language(text: str, requested: Optional[str] = None) -> str:
    """Language of a report.

    A tie keeps ``requested``. The other language is returned only when it
    has a strict majority, which is the only case the caller rejects.
    """
    en = len(_EN_REPORT.findall(text or ""))
    fr = len(_FR_REPORT.findall(text or ""))
    if en > fr:
        return "en"
    if fr > en:
        return "fr"
    if requested in {"en", "fr"}:
        return requested
    if re.search(r"\b(?:the|is|was|this|reached|milestone|treasurer|arrival)\b", text or "", re.I):
        return "en"
    return "fr"


def _normalize_dots(text: str) -> str:
    """One period, then a space when the next sentence is glued on.

    ``250 nm.The boat`` becomes two sentences. ``www.helloasso.com`` stays,
    because the letter after that dot is lowercase.
    """
    cleaned = re.sub(r"\.{2,}", ".", text or "")
    cleaned = re.sub(r"\s+([.!?…])", r"\1", cleaned)
    cleaned = re.sub(r"([.!?…])(?:\s*[.!?…])+", r"\1", cleaned)

    def split_glued(match: re.Match) -> str:
        nxt = match.group(2)
        if nxt.isupper():
            return f"{match.group(1)} {nxt}"
        return match.group(0)

    cleaned = re.sub(r"([.!?…])([A-Za-zÀ-ÿ])", split_glued, cleaned)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def _sentence_words(sentence: str) -> list[str]:
    return re.findall(r"[A-Za-zÀ-ÿ0-9']+", sentence or "")


def _is_cutoff(sentence: str) -> bool:
    """A last sentence cut off on a function word, such as 'I am the.'

    A figure after that word, including a filtered ``[?]``, is a finished claim.
    """
    body = re.sub(r"[.!?…]+$", "", (sentence or "").strip()).strip()
    if re.search(r"(?:\[\?\]|\d+)\s*$", body):
        return False
    words = _sentence_words(body)
    if not words:
        return True
    return words[-1].casefold() in _DANGLING_WORD


def _trim_cutoff(text: str) -> str:
    sentences = _split_sentences(text)
    while sentences and _is_cutoff(sentences[-1]):
        sentences.pop()
    return " ".join(sentences).strip()


def _dedupe_sentences(text: str) -> str:
    kept: list[str] = []
    seen: set[str] = set()
    for sentence in _split_sentences(text):
        key = re.sub(r"\s*:\s*", ":", sentence.casefold())
        key = re.sub(r"\s+", " ", key).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(sentence)
    return " ".join(kept).strip()


def _plain_distance_tokens(text: str, lang: str) -> str:
    """Lightning copies the JSON keys. Readers see plain words."""
    if lang == "en":
        covered, planned = "distance covered", "planned distance"
    else:
        covered, planned = "distance parcourue", "distance prévue"
    cleaned = re.sub(r"\bdistance_nm\b", covered, text or "", flags=re.IGNORECASE)
    return re.sub(r"\bplanned_nm\b", planned, cleaned, flags=re.IGNORECASE)


def _fix_sentence_starts(text: str) -> str:
    """Capitalize after a sentence stop. Dots inside a URL stay as they are.

    ``tracée.en route`` is split because the word before the stop carries an
    accent. ``www.helloasso.com`` does not.
    """
    cleaned = re.sub(
        r"([A-Za-zÀ-ÿ]*[À-ÿ][.!?…])(?=[A-Za-zÀ-ÿ])",
        r"\1 ",
        text or "",
    )

    def upper(match: re.Match) -> str:
        return match.group(1) + match.group(2).upper()

    return re.sub(r"(^|[.!?…]\s+)([a-zà-ÿ])", upper, cleaned)


def _prepare_model_narrative(text: str, lang: str = "fr") -> str:
    """Drop echoed instructions, a repeated Decision line, and a cut-off tail."""
    cleaned = _plain_distance_tokens(text or "", lang)
    cleaned = _strip_signatures(cleaned)
    cleaned = _drop_verbless_signatures(cleaned)
    cleaned = _normalize_dots(cleaned)
    cleaned = _drop_sentences(cleaned, _ECHO_RE)
    cleaned = _drop_sentences(cleaned, _POLICY_RE)
    return _fix_sentence_starts(_dedupe_sentences(_trim_cutoff(cleaned)))


def _finish_text(text: str) -> str:
    return _fix_sentence_starts(_dedupe_sentences(_normalize_dots(text or "")))


def _signature(lang: str) -> str:
    return "— The captain" if lang == "en" else "— Le capitaine"


def _strip_signatures(text: str) -> str:
    """Drop every model sign-off so the reply can add exactly one."""
    cleaned = _drop_sentences(text or "", _INVENTED_SENTENCE)
    cleaned = _LONG_SIGNATURE.sub(" ", cleaned)
    cleaned = _INVENTED_SIGNATURE.sub(" ", cleaned)
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


def _pledge_line(suggested: dict, lang: str) -> str:
    shown = format_amount(suggested.get("amount_eur"), lang)
    exact = (
        f"{suggested['description']} ({shown}), "
        f"{display_name(str(suggested.get('milestone_id') or ''))}, {suggested['intent']}"
    )
    if lang == "en":
        exact = (
            f"{suggested['description']} ({shown}), "
            f"{display_name(str(suggested.get('milestone_id') or ''))}, intent {suggested['intent']}"
        )
        return f"Computed pledge, no charge: {exact}."
    return f"Promesse calculée, sans débit : {exact}."


def _authorize_equivalent(text: str) -> bool:
    """AUTHORIZE, « autorisation », or « intention d'autorisation »."""
    folded = (text or "").casefold().replace("’", "'")
    if "authorize" in folded or "autorisation" in folded:
        return True
    return "intention d'autorisation" in folded


def _port_present(text: str, milestone_id: str) -> bool:
    folded = (text or "").casefold()
    slug = (milestone_id or "").casefold()
    shown = display_name(milestone_id).casefold()
    if slug and slug in folded:
        return True
    return bool(shown) and shown in folded


def _drop_amount_without_port(text: str, suggested: dict) -> str:
    """A pledge amount that never names the port is replaced by the code line."""
    amount = str(suggested.get("amount_eur") or "")
    port = str(suggested.get("milestone_id") or "")
    if not amount:
        return text or ""
    kept = []
    for sentence in _split_sentences(text):
        if amount_in_text(sentence, amount) and not _port_present(sentence, port):
            continue
        kept.append(sentence)
    return " ".join(kept).strip()


def _restates_milestone_or_intent(sentence: str, suggested: dict) -> bool:
    """A label such as ``Jalon : Dakar.`` or ``Intention : autorisation.``"""
    body = re.sub(r"[.!?…]+$", "", (sentence or "").strip()).strip()
    match = re.match(
        r"^(?:jalons?|milestones?|intentions?|intents?|escale|port)\s*:\s*(.*)$",
        body,
        flags=re.IGNORECASE,
    )
    if not match:
        return False
    rest = match.group(1)
    rest = re.sub(
        r"\b(?:autorisation|authorize|authorise)\b",
        " ",
        rest,
        flags=re.IGNORECASE,
    )
    port = str(suggested.get("milestone_id") or "")
    for token in (display_name(port), port, _escale_slug(port)):
        if token:
            rest = re.sub(re.escape(token), " ", rest, flags=re.IGNORECASE)
    return re.sub(r"[^A-Za-zÀ-ÿ0-9]+", "", rest) == ""


def _drop_milestone_intent_labels(text: str, suggested: dict) -> str:
    kept = [
        sentence for sentence in _split_sentences(text)
        if not _restates_milestone_or_intent(sentence, suggested)
    ]
    return " ".join(kept).strip()


def _has_exact_pledge(text: str, suggested: dict) -> bool:
    """True when amount and port are already there, with an authorize wording.

    The catalogue description does not have to be copied verbatim.
    """
    if not amount_in_text(text or "", str(suggested.get("amount_eur") or "")):
        return False
    if not _port_present(text or "", str(suggested.get("milestone_id") or "")):
        return False
    return _authorize_equivalent(text or "")


def _french_lightning_labels(text: str) -> str:
    """Lightning sometimes keeps English labels. French uses a space before the colon."""
    cleaned = re.sub(r"\bMilestones?\s*:\s*", "Jalon : ", text or "", flags=re.IGNORECASE)
    cleaned = re.sub(r"\bmilestones?\b", "jalon", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bIntent\s*:\s*", "Intention : ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bintent\b", "intention", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\b(Jalon|Décision|Intention|Proposition)\s*:",
        r"\1 :",
        cleaned,
    )
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def _french_labels(text: str) -> str:
    """French replies say jalon and intention, for the main model and for Lightning."""
    return _french_lightning_labels(text)


def _fix_port_typos(text: str, milestone_id: str = "") -> str:
    """A misspelled port is shown under its real name."""
    def replace(match: re.Match) -> str:
        word = match.group(0)
        canonical = _canonical_slug(word, milestone_id)
        if not canonical:
            return word
        shown = display_name(canonical)
        if word.casefold() == shown.casefold():
            return word
        return shown

    return re.sub(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ-]{3,}", replace, text or "")


def _heading_toward(text: str) -> str:
    """English not-reached copy says ``heading toward``, never ``is toward``."""
    return re.sub(
        r"\b(is)\s+(?!heading\b)toward\b",
        r"\1 heading toward",
        text or "",
        flags=re.IGNORECASE,
    )


_NAME_WORD = {
    "capitaine", "captain", "bleu", "bleue", "blue", "intelligence",
    "escales", "escale", "le", "la", "les", "the", "de", "of", "l",
}


def _verbless_signature(sentence: str) -> bool:
    """A name plate such as « Capitaine Bleu Intelligence Escales », with no verb."""
    if not re.search(r"capitaine|captain|intelligence", sentence or "", re.I):
        return False
    words = re.findall(r"[A-Za-zÀ-ÿ]+", sentence or "")
    return bool(words) and all(word.casefold() in _NAME_WORD for word in words)


_TRAILING_NAME = re.compile(
    r"(?:[,;—–\-]\s*)?(?:le\s+|the\s+)?(?:capitaine|captain)\s+"
    r"(?:bleu|bleue|blue)\s+intelligence(?:\s+escales)?\s*$",
    re.IGNORECASE,
)


def _drop_verbless_signatures(text: str) -> str:
    kept = []
    for sentence in _split_sentences(text):
        if _verbless_signature(sentence):
            continue
        cleaned = _TRAILING_NAME.sub("", sentence).strip(" ,;:—–-")
        if cleaned:
            kept.append(cleaned)
    return " ".join(kept).strip()


def _standardise_french(text: str) -> str:
    """One wording for the intent and for the treasurer."""
    cleaned = re.sub(
        r"votre\s+intention\s+est\s+authorize\b",
        "intention : autorisation",
        text or "",
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\bintention\s+est\s+authorize\b",
        "intention : autorisation",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\bintent(?:ion)?\s*:\s*authorize\b",
        "intention : autorisation",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\bauthorize\b", "autorisation", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\b(?:the\s+treasurer|(?:le\s+)?tr[ée]sorier)\b",
        "le trésorier",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\b(?:le\s+)+trésorier\b", "le trésorier", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bde\s+le\s+trésorier\b", "du trésorier", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(du|au|ce|un|son|mon)\s+le\s+trésorier\b", r"\1 trésorier", cleaned, flags=re.IGNORECASE)
    return _fix_french_vocabulary(cleaned)


def _fix_french_vocabulary(text: str) -> str:
    """One treasurer sentence. Refunds and the feminine title do not stay."""
    cleaned = re.sub(r"€\s*en\s+euros\b", "€", text or "", flags=re.IGNORECASE)
    kept: list[str] = []
    said = False
    for sentence in _split_sentences(cleaned):
        if re.search(r"remboursement|trésorière", sentence, re.IGNORECASE):
            continue
        decides = re.search(r"trésorier", sentence, re.IGNORECASE) and re.search(
            r"décide|décider|prélev|libér|capture|annul|encaiss|argent",
            sentence,
            re.IGNORECASE,
        )
        if decides:
            if not said:
                kept.append(_TREASURER_DECIDES)
                said = True
            continue
        kept.append(sentence)
    return " ".join(kept).strip()


def _drop_model_pledge(text: str) -> str:
    return _drop_sentences(text, _MODEL_PLEDGE_LINE)


def _drop_standalone_intent(text: str) -> str:
    """``Intent AUTHORIZE.`` alone repeats the pledge line."""
    kept = [
        sentence for sentence in _split_sentences(text)
        if not _STANDALONE_INTENT.match(sentence.strip())
    ]
    return " ".join(kept).strip()


def _miles_to_reached(text: str, milestone_id: str) -> str:
    """On a reached escale, Lightning's ``miles from`` the port becomes ``to``."""
    shown = display_name(milestone_id)
    slug = _escale_slug(milestone_id)

    def repl(match: re.Match) -> str:
        port = match.group(2)
        if _escale_slug(port) == slug or port.casefold() == shown.casefold():
            return f"{match.group(1)} to {port}"
        return match.group(0)

    return re.sub(
        r"((?:nautical\s+)?miles?)\s+from\s+([A-Za-zÀ-ÿ][\wÀ-ÿ-]*)",
        repl,
        text or "",
        flags=re.IGNORECASE,
    )


def _period_after_link(text: str, url: str) -> str:
    """A membership link ends the sentence when more text follows."""
    if not url or url not in (text or ""):
        return text or ""
    return re.sub(
        re.escape(url) + r"(?!\s*[.!?…])(\s+)(?=\S)",
        url + r".\1",
        text,
    )


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
    # Keep the French space before a colon (Jalon :). Other marks stay tight.
    cleaned = re.sub(r"\s+([,.;!?…])", r"\1", cleaned)
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


_MONTHS_EN = (
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
_MONTHS_FR = (
    "", "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)
_ARRIVAL_KEYS = (
    "arrived", "arrival", "arrived_at", "arrival_at",
    "arrival_date", "arrival_time", "arrival_iso",
)
_HIDDEN_FROM_MODEL = {"recorded_at", "at", "created_at"}


def _evidence_for_model(evidence: dict) -> dict:
    """Drop the registration clock and every arrival field. Code formats the date."""
    if not isinstance(evidence, dict):
        return {}
    hidden = _HIDDEN_FROM_MODEL | set(_ARRIVAL_KEYS)
    cleaned: dict = {}
    for key, value in evidence.items():
        if key in hidden:
            continue
        if key == "facts" and isinstance(value, dict):
            cleaned[key] = {
                fact_key: fact_value
                for fact_key, fact_value in value.items()
                if fact_key not in hidden
            }
        else:
            cleaned[key] = value
    return cleaned


def arrival_phrase(evidence: dict, lang: str = "fr") -> str:
    """Formatted arrival from evidence.facts only. recorded_at is never read."""
    facts = evidence.get("facts") if isinstance(evidence, dict) else None
    if not isinstance(facts, dict):
        return ""
    raw = ""
    for key in _ARRIVAL_KEYS:
        value = facts.get(key)
        if value:
            raw = str(value).strip()
            break
    if not raw:
        return ""
    text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        return ""
    if moment.tzinfo is not None:
        moment = moment.astimezone(dt.timezone.utc)
    has_time = bool(re.search(r"[T\s]\d{1,2}:\d{2}", raw))
    clock = f"{moment.hour:02d}:{moment.minute:02d}"
    if lang == "en":
        date = f"{moment.day} {_MONTHS_EN[moment.month]} {moment.year}"
        if has_time:
            return f"on {date} at {clock} UTC"
        return f"on {date}"
    day = "1er" if moment.day == 1 else str(moment.day)
    date = f"{day} {_MONTHS_FR[moment.month]} {moment.year}"
    if has_time:
        return f"le {date} à {clock} UTC"
    return f"le {date}"


def _reached_sentence(milestone_id: str, lang: str, arrival: str) -> str:
    """The only reached sentence. Code writes it, with the formatted arrival."""
    port = display_name(milestone_id)
    if lang == "en":
        if arrival:
            return f"Milestone {port} was reached {arrival}, with no remaining distance."
        return f"Milestone {port} was reached, with no remaining distance."
    if arrival:
        return f"L'escale {port} est atteinte {arrival}, sans distance restante."
    return f"L'escale {port} est atteinte, sans distance restante."


def _is_bare_leg(sentence: str, milestone_id: str) -> bool:
    shown = display_name(milestone_id)
    body = (sentence or "").strip().rstrip(".").strip()
    pattern = (
        rf"(?:milestone|jalon|escale|port)\s+"
        rf"(?:{re.escape(shown)}|{re.escape(milestone_id)})$"
    )
    return bool(re.fullmatch(pattern, body, flags=re.IGNORECASE))


def _assert_reached(text: str, milestone_id: str, lang: str, arrival: str = "") -> str:
    """Code fact first, then at most one model sentence that does not restate it."""
    kept = []
    for sentence in _split_sentences(text):
        if (
            _AWAY_CLAIM.search(sentence)
            or _REACHED_CLAIM.search(sentence)
            or _HAS_DATE.search(sentence)
        ):
            continue
        if _is_bare_leg(sentence, milestone_id):
            continue
        kept.append(sentence)
    fact = _reached_sentence(milestone_id, lang, arrival)
    return " ".join([fact, *kept[:1]])


def _capitalize_ports(text: str, milestone_id: str) -> str:
    slug = (milestone_id or "").strip()
    if not slug:
        return text or ""
    shown = display_name(slug)
    return re.sub(re.escape(slug), shown, text or "", flags=re.IGNORECASE)


def _word_count(text: str) -> int:
    return len((text or "").split())


def _fit_words(prose: str, required: list[str], limit: int = _CHAT_WORD_LIMIT) -> str:
    """Keep the required tail. Drop a whole sentence rather than cut one off."""
    prose = _trim_cutoff(_normalize_dots(prose or ""))
    tail = [part.strip() for part in required if part and part.strip()]
    tail_text = " ".join(tail)

    def too_long(body: str) -> bool:
        return _word_count(f"{body} {tail_text}".strip()) > limit

    while prose and too_long(prose):
        sentences = _split_sentences(prose)
        if len(sentences) > 1:
            prose = " ".join(sentences[:-1]).strip()
            continue
        prose = ""
        break
    prose = _trim_cutoff(prose)
    parts = [prose] if prose else []
    parts.extend(tail)
    return _finish_text(" ".join(parts))


def _compose_chat_reply(
    model_text: str,
    suggested: Optional[dict],
    url: str,
    lang: str,
    *,
    treasurer: bool,
    ask_escale: bool = False,
) -> str:
    """Pledge repeated exactly, one signature, at most 80 words."""
    if treasurer or not suggested:
        if treasurer:
            if lang == "en":
                prose = "This question belongs to the treasurer review. The captain does not decide it."
            else:
                prose = "Cette question relève de la revue du trésorier. Le capitaine ne la tranche pas."
        elif ask_escale:
            if lang == "en":
                prose = "Which escale? Name the stop and I will compute the pledge."
            else:
                prose = "Quelle escale ? Indiquez son nom pour que je calcule la promesse."
        elif lang == "en":
            prose = "This question is about status. The captain does not suggest a pledge."
        else:
            prose = "Cette question porte sur le statut. Le capitaine ne propose pas de promesse."
        return _fit_words("", [prose, _signature(lang)])
    prose = _prepare_model_narrative(model_text, lang)
    port_id = str(suggested.get("milestone_id") or "")
    prose = _fix_port_typos(prose, port_id)
    prose = _clean_model_urls(prose, url)
    prose = _period_after_link(prose, url)
    prose = _drop_sentences(prose, _CHAT_DECIDE_RE)
    prose = _trim_cutoff(_normalize_dots(prose))
    if lang == "fr":
        prose = _standardise_french(_french_labels(prose))
    elif lang == "en":
        prose = _heading_toward(prose)
    prose = _drop_amount_without_port(prose, suggested)
    prose = _drop_model_pledge(prose)
    prose = _drop_milestone_intent_labels(prose, suggested)
    prose = _drop_standalone_intent(prose)
    required: list[str] = [_pledge_line(suggested, lang)]
    joined = " ".join(required)
    if lang == "en" and not re.search(r"\bintent\s+authorize\b", f"{prose} {joined}", re.I):
        required.append("intent AUTHORIZE.")
    if url and url not in prose and url not in " ".join(required):
        required.append(_membership_line(url, lang))
    required.append(_signature(lang))
    reply = _fit_words(prose, required)
    port = str(suggested.get("milestone_id") or "") if suggested else ""
    reply = _fix_port_typos(_capitalize_ports(reply, port), port)
    reply = _period_after_link(reply, url)
    if lang == "fr":
        reply = _standardise_french(reply)
    return _fix_sentence_starts(reply)


def _without_jalon(text: str, lang: str) -> str:
    """English reports say Milestone. French reports keep Jalon."""
    if lang != "en":
        return text
    return re.sub(r"\bJalons?\b", "Milestone", text or "", flags=re.IGNORECASE)


def _shape_report(
    text: str,
    milestone_id: str,
    lang: str = "fr",
    name_leg: bool = True,
    drop_distance_left: bool = True,
) -> str:
    """No title. When the leg name is missing, prefix the first sentence."""
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
        sentences = [_heading_toward(_without_jalon(sentence, "en")) for sentence in sentences]
        if not drop_distance_left:
            sentences = [_miles_to_reached(sentence, milestone_id) for sentence in sentences]
    sentences = [
        sentence for sentence in sentences
        if not _AWAY_CLAIM.search(sentence)
        and not _MILES_AWAY.search(sentence)
        and not _HAS_DATE.search(sentence)
        and not (drop_distance_left and _MILES_FROM.search(sentence))
        and not _distance_without_unit(sentence)
    ]
    shown = display_name(milestone_id)
    blob = " ".join(sentences).casefold()
    named = milestone_id.casefold() in blob or shown.casefold() in blob
    if name_leg and sentences and not named:
        first = sentences[0].strip()
        if lang == "en":
            sentences[0] = f"Milestone {shown}: {first}"
        elif first:
            sentences[0] = f"Escale {shown} : {first[0].lower()}{first[1:]}"
        else:
            sentences[0] = f"Escale {shown} : {first}"
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
    started = time.monotonic()
    try:
        raw = await llm.ask_text(
            prompt, system=system, max_tokens=max_tokens, temperature=temperature,
        )
    except Exception as exc:
        from app.core.llm import safe_error_message

        log.warning(
            "captain llm failed in %.3fs (%s): %s",
            time.monotonic() - started,
            type(exc).__name__,
            safe_error_message(exc),
        )
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


def _forced_lang(lang: Optional[str]) -> Optional[str]:
    token = (lang or "").strip().lower()
    if token.startswith("en"):
        return "en"
    if token.startswith("fr"):
        return "fr"
    return None


async def _narrative_for_language(
    prompt: str,
    milestone_id: str,
    lang: Optional[str],
    reached: bool,
) -> tuple[str, dict[str, str], str]:
    """Up to two attempts. A forced language retries once, then the rules apply."""
    forced = _forced_lang(lang)
    prompt_lang = forced or "fr"
    system = _report_system(milestone_id, reached, prompt_lang)

    async def once(instruction: str) -> tuple[str, str, dict[str, str]]:
        narrative, source = await _llm_text(
            prompt,
            instruction,
            max_tokens=_REPORT_MAX_TOKENS,
            temperature=_REPORT_TEMPERATURE,
        )
        raw = narrative or ""
        usable = _prepare_model_narrative(raw, prompt_lang) if raw else ""
        return raw, usable, source

    raw, usable, source = await once(system)
    if not usable:
        log.warning("captain report rejected (empty narrative) raw=%s", raw)
        return "", source, prompt_lang
    detected = _report_language(usable, forced)
    if forced is None or detected == forced:
        if (forced or detected) == "fr":
            usable = _standardise_french(_french_labels(usable))
        return usable, source, forced or detected
    log.warning(
        "captain report rejected (language %s != %s) raw=%s",
        detected, forced, raw,
    )
    reminder = (
        " RAPPEL : écris en français uniquement."
        if forced == "fr"
        else " Write in English only."
    )
    raw, usable, source = await once(f"{system}{reminder}")
    if usable and _report_language(usable, forced) == forced:
        if forced == "fr":
            usable = _standardise_french(_french_labels(usable))
        return usable, source, forced
    log.warning(
        "captain report rejected (language %s != %s after retry) raw=%s",
        _report_language(usable, forced) if usable else "empty",
        forced,
        raw,
    )
    return "", _rules_source(), forced


async def review(
    milestone_id: str,
    reader: Optional[ReadOnlyTools] = None,
    lang: Optional[str] = None,
) -> dict:
    """Propose capture or void from evidence. Does not execute either."""
    report_lang = _forced_lang(lang) or "fr"
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
    visible = _evidence_for_model(evidence)
    allowed = {
        "evidence": visible,
        "milestone_id": milestone_id,
        "decision": decision,
        "language": report_lang,
    }
    prompt = json.dumps(allowed, ensure_ascii=False, default=str)
    usable, source, report_lang = await _narrative_for_language(
        prompt, milestone_id, _forced_lang(lang), reached,
    )
    model_lost = not usable
    if not usable:
        narrative = _fallback_report(milestone_id, decision, evidence, lang=report_lang)
        source = _rules_source()
    else:
        usable = _fix_port_typos(usable, milestone_id)
        if report_lang == "en":
            usable = _heading_toward(usable)
        narrative = _shape_report(
            usable,
            milestone_id,
            report_lang,
            name_leg=not reached,
            drop_distance_left=not reached,
        )
        if not narrative.strip():
            log.warning(
                "captain report rejected (date or distance filter removed every sentence) raw=%s",
                usable,
            )
            narrative = _fallback_report(milestone_id, decision, evidence, lang=report_lang)
            source = _rules_source()
            model_lost = True
    narrative = _finish_text(narrative)
    narrative = _without_jalon(filter_numbers(narrative, allowed, lang=report_lang), report_lang)
    if reached:
        narrative = _assert_reached(
            narrative,
            milestone_id,
            report_lang,
            arrival_phrase(evidence, report_lang),
        )
    if model_lost and report_lang == "fr":
        factual = _covered_miles_sentence(evidence, "fr")
        if factual and factual not in narrative:
            narrative = _finish_text(f"{narrative} {factual}")
    narrative = _capitalize_ports(_finish_text(narrative), milestone_id)
    decision_line = (
        f" Decision: {decision}." if report_lang == "en" else f" Décision : {decision}."
    )
    justification = _capitalize_ports(
        _finish_text(f"{narrative}{decision_line}"),
        milestone_id,
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
    ask_escale = suggested is None and not treasurer and not _is_status_question(text)
    allowed = {"message": text, "suggested": suggested, "membership_url": url}
    if treasurer or suggested is None:
        # Do not send this question to a model: the horizon rule stays in code.
        raw, source = "", _rules_source()
    else:
        prompt = json.dumps(allowed, ensure_ascii=False, default=str)
        raw, source = await _llm_text(
            prompt, _chat_system(lang), max_tokens=_CHAT_MAX_TOKENS, temperature=_CHAT_TEMPERATURE,
        )
        if raw:
            if lang == "fr":
                raw = _french_labels(raw)
            raw = filter_numbers(raw, allowed, lang=lang)
        else:
            raw, source = "", _rules_source()
    reply = _compose_chat_reply(
        raw or "", suggested, url, lang, treasurer=treasurer, ask_escale=ask_escale,
    )
    return {
        "reply": reply,
        "membership_url": url,
        "suggested_pledge": suggested,
        "model_source": source,
    }
