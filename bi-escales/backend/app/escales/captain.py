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
from zoneinfo import ZoneInfo

from .config import AUTH_MAX_DAYS, membership_url, simulated_now
from .paypal_txn_search import default_transaction_search_window
from .milestones import (
    amount_in_text,
    decision_for,
    decision_for_evidence,
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
    r"|my|you|your|will|is|are|was|old|days?|authorization|it|this"
    r"|how|much|price|cost|costs|cabin)\b",
    re.IGNORECASE,
)
_FR_HINT = re.compile(
    r"\b(?:je|j'|voudrais|parrain\w*|milles?|près|pres|pour|dîner|diner|une|des|autorisation|est-ce"
    r"|combien|co[uû]te|prix|cabine)\b",
    re.IGNORECASE,
)
_TREASURER_Q = re.compile(
    r"encaiss|annul|captur|void|tr[ée]sorier|treasurer|authori[sz]ation|autorisation",
    re.IGNORECASE,
)
# Timing of a capture. A request to capture or void one authorization stays with the treasurer.
_CAPTURE_RULE_Q = re.compile(
    r"\bwhen\b.{0,80}\bcaptur"
    r"|\bquand\b.{0,80}\bcaptur"
    r"|\bwhen\b.{0,40}\bmoney\b.{0,40}\b(?:taken|charged|captured)"
    r"|\bwill\b.{0,60}\bmoney\b.{0,40}\b(?:taken|charged|captured)"
    r"|\bmoney\b.{0,40}\b(?:taken|captured)\b.{0,40}\bdeparture"
    r"|\bquand\b.{0,40}\bargent\b.{0,40}\b(?:pr[ée]lev|encaiss|pris)"
    r"|\bargent\b.{0,50}\b(?:pris|pr[ée]lev|encaiss).{0,40}\bd[ée]part"
    r"|\bmon argent\b.{0,40}\bd[ée]part"
    r"|\bmy money\b.{0,40}\bdeparture",
    re.IGNORECASE | re.DOTALL,
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
_REFUSAL_RE = re.compile(
    r"rel[èe]ve de la revue du tr[ée]sorier|ne la tranche pas|"
    r"belongs to the treasurer review|does not decide it|"
    r"porte sur le statut|does not suggest a pledge|"
    r"which escale|quelle escale",
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


def _is_capture_rule_question(message: str) -> bool:
    """When money is captured. Not a request to capture or void one pledge."""
    text = message or ""
    if re.search(r"\bvoid\b|\bannuler\b|ou l['’]annul", text, re.IGNORECASE):
        return False
    return bool(_CAPTURE_RULE_Q.search(text))


def _public_rule(lang: str) -> str:
    """Authorize near departure, capture that day, void if cancelled, Vault past 29 days."""
    if lang == "en":
        return (
            "A pledge is authorized as close to departure as possible. "
            "The money is captured on the departure day. "
            "If the stopover is cancelled, the authorization is voided. "
            "When the departure is more than 29 days away, the pledge uses PayPal Vault."
        )
    return (
        "Une promesse est autorisée au plus près du départ. "
        "L'argent est capturé le jour du départ. "
        "Si l'escale est annulée, l'autorisation est annulée. "
        "Quand le départ est à plus de 29 jours, la promesse utilise PayPal Vault."
    )


def _capture_rule_reply(lang: str) -> str:
    """The public rule. It does not send the reader only to the treasurer."""
    return _fit_words("", [_public_rule(lang), _signature(lang)])


def _is_treasurer_question(message: str) -> bool:
    if _is_capture_rule_question(message):
        return False
    return bool(_TREASURER_Q.search(message or ""))


def _is_status_question(message: str) -> bool:
    return bool(_STATUS_Q.search(message or ""))


def _no_pledge_suggestion(message: str) -> bool:
    """Treasurer and status questions are not a pledge to price.

    A sentence that already prices a line is still a pledge: the reply
    shows that line and does not refuse.
    """
    if _message_prices_a_pledge(message):
        return False
    return (
        _is_treasurer_question(message)
        or _is_status_question(message)
        or _is_fund_question(message)
    )


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
    from .naviguide_bridge import clock_legs

    for leg in clock_legs():
        title = f"{leg.get('from_name')} → {leg.get('to_name')}"
        table[str(leg.get("id") or "")] = title
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
    """One catalogue line. The figure is indicative, never the charged amount.

    ``project_pledge`` and ``common_fund`` have no unit price: the visitor's
    amount stays as written. The other kinds show a simulated unit. A pledge
    of that kind must be at least that unit.
    """
    row = {
        "kind": kind,
        "currency": "EUR",
        "label": SIMULATED_PRICE_LABEL,
        "simulated": True,
        "indicative": True,
    }
    amount = _SIMULATED_EUR.get(kind)
    if amount is None:
        row["free_amount"] = True
    else:
        row["amount_eur"] = f"{amount:.2f}"
        row["free_amount"] = False
    return row


def simulated_prices() -> dict:
    """One row per pledge kind. Prices are indicative; the visitor's amount stays."""
    return {
        "simulated": True,
        "indicative": True,
        "label": SIMULATED_PRICE_LABEL,
        "note": "Prices are indicative. The visitor's amount is what PayPal authorizes.",
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
            "Use only numbers and facts present in the JSON. Do not invent a figure or a fact. "
            "The only date you may write is arrival_iso, copied exactly. "
            "distance_nm is the distance covered and planned_nm the planned distance. "
            "Write nautical miles or nm immediately after every distance number from the JSON. Never write nm alone. "
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
        "Utilise seulement les nombres et les faits présents dans le JSON. N'invente aucun chiffre ni aucun fait. "
        "La seule date permise est arrival_iso, recopiée telle quelle. "
        "distance_nm est la distance parcourue et planned_nm la distance prévue. "
        "Écris milles ou nm juste après chaque nombre de distance du JSON. N'écris jamais nm seul. "
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


def _chat_system_en() -> str:
    return (
        "You are the Blue Intelligence Escales captain. Reply in English only. "
        "Repeat the computed pledge exactly: amount, currency, description, stopover and intent. "
        "Do not propose to take or release money. Do not create an order. Do not invent a price. "
        "State only facts present in the JSON: the stopover, the fund, and the computed pledge. "
        "Do not invent a date. Do not write a date. The code appends the schedule dates. "
        "If a fact is absent, say you do not know. Do not describe the place. "
        "A pledge is authorized as close to departure as possible. "
        "The money is captured on the departure day. "
        "If the stopover is cancelled, the authorization is voided. "
        "Do not send the reader to the treasurer for that rule. "
        "Mention membership only by repeating the HelloAsso URL you were given. "
        "If no URL was given, do not mention membership and do not write any URL. "
        "Write complete sentences and never stop mid-sentence. "
        "Sign once, and do not repeat your name. At most 80 words."
    )


def _chat_system_fr() -> str:
    return (
        "Tu es le capitaine de Blue Intelligence Escales. Réponds uniquement en français. "
        "Répète la promesse calculée telle quelle : montant, devise, description et escale. "
        "Ne propose pas de prendre ou de libérer l'argent. Ne crée pas d'ordre. N'invente pas de prix. "
        "Énonce seulement les faits présents dans le JSON : l'escale, la caisse et la promesse calculée. "
        "N'invente pas de date. N'écris aucune date. Le code ajoute les dates de l'escale. "
        "Si un fait manque, dis que tu ne sais pas. Ne décris pas le lieu. "
        "Une promesse est autorisée au plus près du départ. "
        "L'argent est capturé le jour du départ. "
        "Si l'escale est annulée, l'autorisation est annulée. "
        "N'envoie pas le lecteur vers le trésorier pour cette règle. "
        "Mentionne l'adhésion seulement en répétant l'URL HelloAsso qu'on t'a donnée. "
        "Sans URL, ne parle pas d'adhésion et n'écris aucune URL. "
        "Écris des phrases complètes et ne t'arrête jamais au milieu d'une phrase. "
        "Signe une seule fois, sans répéter ton nom. Au plus 80 mots."
    )


def _chat_system(lang: str) -> str:
    if lang == "en":
        return _chat_system_en()
    if lang == "fr":
        return _chat_system_fr()
    return _chat_system_en()


def resolve_chat_lang(
    message: str,
    requested: Optional[str] = None,
    accept_language: str = "",
) -> str:
    """App language wins. Then the message when clear. Then Accept-Language. Unknown is English."""
    if (requested or "").strip():
        return _forced_lang(requested) or "en"
    en = len(_EN_HINT.findall(message or ""))
    fr = len(_FR_HINT.findall(message or ""))
    if en > fr:
        return "en"
    if fr > en:
        return "fr"
    token = (accept_language or "").split(",")[0].split(";")[0].strip()
    header = _forced_lang(token)
    if header:
        return header
    return message_lang(message)


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
    """Canonical milestone id named in the message.

    Accents, dashes, spaces, and case do not matter: Pointe-à-Pitre,
    pointe a pitre, and POINTEAPITRE are the same stop. The id is the
    route id (``dep-dzaoudzi-mayotte``), not the short chat slug.
    """
    from .naviguide_bridge import resolve_milestone

    match = _PLACE.search(message or "")
    token = match.group(1) if match else (message or "")
    found = resolve_milestone(token)
    if found:
        return found
    close = _canonical_slug(token)
    if close:
        found = resolve_milestone(close)
        if found:
            return found
    return resolve_milestone(message or "") if match else None


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


def _mile_cap(place: str) -> Optional[Decimal]:
    """Whole nautical miles of the real outgoing leg. None when the leg is not measured."""
    from .naviguide_bridge import leg_by_id, leg_departing_from, leg_distance_nm

    leg = leg_by_id(place) if str(place or "").startswith("leg-") else None
    if leg is None:
        leg = leg_departing_from(place)
    if not leg:
        return None
    distance = leg_distance_nm(str(leg.get("id") or ""))
    if distance is None or distance < 1:
        return None
    return Decimal(int(distance))


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
    for match in _MILES.finditer(_with_written_numbers(text)):
        try:
            count = Decimal(match.group(1).replace(",", "."))
        except InvalidOperation:
            continue
        if count > 0:
            counts.append(count)
    dinners = _explicit_dinners(text)
    if not counts and dinners == 0:
        counts = [Decimal("1")]
    total_miles = sum(counts, Decimal("0"))
    cap = _mile_cap(place) if total_miles > 0 else None
    if cap is not None and total_miles > cap:
        total_miles = cap
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


# The model still writes this. Ordinary replies use the public capture rule instead.
_TREASURER_ONLY = re.compile(
    r"only the treasurer decides"
    r"|the treasurer (?:will |must )?decides?"
    r"|seul le tr[ée]sorier d[ée]cide"
    r"|(?:le\s+)?tr[ée]sorier\s+(?:doit\s+|va\s+)?(?:d[ée]cid|tranch)",
    re.IGNORECASE,
)
# A model claim that money will move. The rules text replaces that reply.
_CHARGE_CLAIM = re.compile(
    r"s(?:era(?:it|s|ient)?|erez|erons|eront)\s+d[ée]bit"
    r"|va(?:s|ont)?\s+(?:être\s+)?d[ée]bit"
    r"|vous\s+(?:ser(?:ez|a)|allez\s+être)\s+d[ée]bit"
    r"|s(?:era(?:it|s|ient)?|erez|erons|eront)\s+(?:pr[ée]lev|encaiss)"
    r"|will\s+be\s+(?:charg|debit)"
    r"|(?:you(?:'|’)ll|you\s+will|going\s+to)\s+be\s+(?:charg|debit)"
    r"|will\s+charge\b",
    re.IGNORECASE,
)


def _fallback_report(milestone_id: str, decision: str, evidence: dict, lang: str = "fr") -> str:
    source = evidence.get("source") or "simulation"
    provider = evidence.get("provider") or "NAVIGUIDE"
    flag = evidence.get("flag") or "simulation"
    port = display_name(milestone_id)
    if lang == "en":
        return (
            f"Milestone {port}: {provider} evidence marked {flag} "
            f"(source {source}). Proposal: {decision}. "
            f"{_public_rule('en')}"
        )
    return (
        f"Jalon {port} : la preuve {provider} porte la marque {flag} (source {source}). "
        f"La proposition est {decision}. "
        f"{_public_rule('fr')}"
    )


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
    cleaned = _drop_broken_fragments(_plain_distance_tokens(text or "", lang))
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
    """French replies say jalon, escale and étape, for the main model and for Lightning."""
    cleaned = _french_lightning_labels(text)
    cleaned = re.sub(r"\bstopovers?\b", "escale", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\blegs?\b", "étape", cleaned, flags=re.IGNORECASE)
    return cleaned


def _english_labels(text: str) -> str:
    """English replies say stopover. The project name Escales stays."""
    return re.sub(r"\bescale\b", "stopover", text or "", flags=re.IGNORECASE)


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
    for sentence in _split_sentences(cleaned):
        if re.search(r"remboursement|trésorière", sentence, re.IGNORECASE):
            continue
        decides = re.search(r"trésorier", sentence, re.IGNORECASE) and re.search(
            r"d[ée]cid|decid|tranch|pr[ée]lev|lib[ée]r|capture|void|annul|encaiss|argent|money",
            sentence,
            re.IGNORECASE,
        )
        if decides:
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
    """Pledge repeated exactly, one signature, at most 80 words.

    Ordinary replies end with the public capture rule.
    A question about one authorization still belongs to the treasurer review.
    A charge claim is dropped and the rules text is used instead.
    """
    if not suggested:
        if treasurer:
            if lang == "en":
                prose = "This question belongs to the treasurer review. The captain does not decide it."
            else:
                prose = "Cette question relève de la revue du trésorier. Le capitaine ne la tranche pas."
            return _fit_words("", [prose, _signature(lang)])
        elif ask_escale:
            if lang == "en":
                prose = "Which stopover? Name the stop and I will compute the pledge."
            else:
                prose = "Quelle escale ? Indiquez son nom pour que je calcule la promesse."
        elif lang == "en":
            prose = "This question is about status. The captain does not suggest a pledge."
        else:
            prose = "Cette question porte sur le statut. Le capitaine ne propose pas de promesse."
        return _fit_words("", [prose, _public_rule(lang), _signature(lang)])
    charged = bool(_CHARGE_CLAIM.search(model_text or ""))
    if charged:
        prose = ""
    else:
        prose = _prepare_model_narrative(model_text, lang)
    port_id = str(suggested.get("milestone_id") or "")
    prose = _fix_port_typos(prose, port_id)
    prose = _clean_model_urls(prose, url)
    prose = _period_after_link(prose, url)
    prose = _drop_sentences(prose, _CHAT_DECIDE_RE)
    prose = _drop_sentences(prose, _REFUSAL_RE)
    prose = _drop_sentences(prose, _TREASURER_ONLY)
    prose = _trim_cutoff(_normalize_dots(prose))
    if lang == "fr":
        prose = _standardise_french(_french_labels(prose))
    elif lang == "en":
        prose = _heading_toward(_english_labels(prose))
    prose = _drop_amount_without_port(prose, suggested)
    prose = _drop_model_pledge(prose)
    prose = _drop_milestone_intent_labels(prose, suggested)
    prose = _drop_standalone_intent(prose)
    required: list[str] = [_pledge_line(suggested, lang)]
    dates = _code_dates_sentence(str(suggested.get("milestone_id") or ""), lang)
    if dates:
        prose = _drop_date_sentences(prose)
        if dates.casefold() not in (prose or "").casefold():
            required.append(dates)
    rules = _public_rule(lang)
    if rules.casefold() not in (prose or "").casefold():
        required.append(rules)
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
    elif lang == "en":
        reply = _english_labels(reply)
    return _fix_sentence_starts(reply)


def _without_unknown_marks(text: str) -> str:
    """Remove ``[?]`` left by the number filter. Allowed figures stay."""
    cleaned = (text or "").replace("[?]", "")
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([.,;])", r"\1", cleaned)
    return cleaned.strip()


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


_BARE_UNIT = re.compile(r"\b(nm|milles?|km)\b", re.IGNORECASE)
_MONTH_INDEX = {}
for _month_number, _pair in enumerate(zip(_MONTHS_EN, _MONTHS_FR), start=0):
    for _name in _pair:
        if _name:
            _MONTH_INDEX[_name.casefold()] = _month_number
_MONTH_INDEX.update({"fevrier": 2, "aout": 8, "decembre": 12, "mai": 5, "may": 5})
_MONTH_WORD = (
    "janvier|février|fevrier|mars|avril|juin|juillet|août|aout|septembre|"
    "octobre|novembre|décembre|decembre|january|february|march|april|june|"
    "july|august|september|october|november|december"
)
# ``may`` / ``mai`` count only beside a day or a year, so the verb stays.
_DATE_PHRASE = re.compile(
    rf"(?:\b(?:in|on|le|au|en|du)\s+)?"
    rf"(?:"
    rf"\d{{4}}-\d{{2}}-\d{{2}}(?:[T ][\d:.Z+-]+)?"
    rf"|\d{{1,2}}(?:er)?\s+(?:{_MONTH_WORD}|mai|may)(?:\s+\d{{4}})?"
    rf"|(?:{_MONTH_WORD})\s+\d{{4}}"
    rf"|(?:mai|may)\s+\d{{4}}"
    rf"|(?:1[89]\d{{2}}|20\d{{2}})"
    rf")\b",
    re.IGNORECASE,
)
_BROKEN_LEAD = re.compile(
    r"(?:^|(?<=[.!?…]\s))((?:[A-Za-zÀ-ÿ]+\s+){0,3}[A-Za-zÀ-ÿ]+),\s*",
)


def _schedule_arrival(milestone_id: str) -> str:
    """Arrival from the frozen clock. Empty when this id is not on the schedule."""
    from .naviguide_bridge import clock_legs, local_schedule_export, resolve_milestone

    wanted = {str(milestone_id or "").strip()}
    resolved = resolve_milestone(milestone_id)
    if resolved:
        wanted.add(resolved)
    for row in local_schedule_export().get("escales") or []:
        if row.get("milestone_id") in wanted and row.get("arrival_iso"):
            return str(row["arrival_iso"])
    for leg in clock_legs():
        if leg.get("id") in wanted and leg.get("arrival_iso"):
            return str(leg["arrival_iso"])
    return ""


def _milestone_in_payload(data: dict) -> str:
    milestone = str(data.get("milestone_id") or "").strip()
    suggested = data.get("suggested")
    if not milestone and isinstance(suggested, dict):
        milestone = str(suggested.get("milestone_id") or "").strip()
    return milestone


def _schedule_slice(milestone_id: str) -> dict[str, str]:
    """Arrival and departure that GET /schedule publishes for this stop or leg.

    The stop arrival is the export row. A leg uses that leg's own pair.
    The next port's arrival is not included.
    """
    from .naviguide_bridge import leg_by_id, leg_departing_from

    if not milestone_id:
        return {}
    arrival = _schedule_arrival(milestone_id)
    departure = ""
    leg = leg_by_id(milestone_id)
    if leg:
        departure = str(leg.get("departure_iso") or "")
        if not arrival:
            arrival = str(leg.get("arrival_iso") or "")
    else:
        outgoing = leg_departing_from(milestone_id)
        if outgoing:
            departure = str(outgoing.get("departure_iso") or "")
    block: dict[str, str] = {}
    if arrival:
        block["arrival_iso"] = arrival
    if departure:
        block["departure_iso"] = departure
    return block


def _with_known_facts(prompt: str) -> str:
    """Add the /schedule dates and the evidence distance. Nothing else is invented."""
    try:
        data = json.loads(prompt)
    except (TypeError, ValueError):
        return prompt
    if not isinstance(data, dict):
        return prompt
    milestone = _milestone_in_payload(data)
    schedule = _schedule_slice(milestone) if milestone else {}
    if schedule:
        data["schedule"] = schedule
        if not data.get("arrival_iso") and schedule.get("arrival_iso"):
            data["arrival_iso"] = schedule["arrival_iso"]
        if not data.get("departure_iso") and schedule.get("departure_iso"):
            data["departure_iso"] = schedule["departure_iso"]
    evidence = data.get("evidence") if isinstance(data.get("evidence"), dict) else {}
    facts = evidence.get("facts") if isinstance(evidence.get("facts"), dict) else {}
    for key in ("distance_nm", "planned_nm"):
        if data.get(key) in (None, "") and facts.get(key) not in (None, ""):
            data[key] = facts[key]
    return json.dumps(data, ensure_ascii=False, default=str)


def _parse_clock(raw: str) -> Optional[dt.datetime]:
    text = (raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        try:
            moment = dt.datetime.fromisoformat(text[:10] + "T00:00:00+00:00")
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.astimezone(dt.timezone.utc)


def _schedule_departure(milestone_id: str) -> str:
    """Departure from the frozen clock for this stop or this leg."""
    moment = _primary_moment(milestone_id)
    if moment is None:
        return ""
    return moment.replace(microsecond=0).isoformat()


def _primary_moment(milestone_id: str) -> Optional[dt.datetime]:
    """The departure this id sails on, else its arrival."""
    labeled = _labeled_moments(milestone_id)
    for kind, moment in labeled:
        if kind == "departure":
            return moment
    for _kind, moment in labeled:
        return moment
    return None


def _labeled_moments(milestone_id: str) -> list[tuple[str, dt.datetime]]:
    """Departure and arrival instants that belong to this stop or leg."""
    from .naviguide_bridge import clock_legs, local_schedule_export, resolve_milestone

    wanted = {str(milestone_id or "").strip()}
    resolved = resolve_milestone(milestone_id) if milestone_id else None
    if resolved:
        wanted.add(resolved)
    slug = _escale_slug(resolved or milestone_id)
    rows: list[tuple[str, dt.datetime]] = []
    for leg in clock_legs():
        leg_id = str(leg.get("id") or "")
        from_slug = _escale_slug(str(leg.get("from_slug") or ""))
        to_slug = _escale_slug(str(leg.get("to_slug") or ""))
        if leg_id in wanted or slug in {from_slug, to_slug}:
            departure = _parse_clock(str(leg.get("departure_iso") or ""))
            arrival = _parse_clock(str(leg.get("arrival_iso") or ""))
            if departure and (leg_id in wanted or from_slug == slug):
                rows.append(("departure", departure))
            if arrival and (leg_id in wanted or to_slug == slug):
                rows.append(("arrival", arrival))
    for row in local_schedule_export().get("escales") or []:
        if row.get("milestone_id") in wanted:
            arrival = _parse_clock(str(row.get("arrival_iso") or ""))
            if arrival:
                rows.append(("arrival", arrival))
    unique: list[tuple[str, dt.datetime]] = []
    seen: set[tuple[str, str]] = set()
    for kind, moment in rows:
        key = (kind, moment.date().isoformat())
        if key in seen:
            continue
        seen.add(key)
        unique.append((kind, moment))
    return unique


def _known_payload(known: str) -> dict:
    try:
        data = json.loads(known or "")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _schedule_moments(known: str) -> tuple[list[dt.datetime], Optional[dt.datetime], Optional[dt.datetime]]:
    """Civil instants injected from /schedule, plus arrival and departure."""
    data = _known_payload(known)
    schedule = data.get("schedule") if isinstance(data.get("schedule"), dict) else {}
    source = schedule or data
    moments: list[dt.datetime] = []
    arrival = _parse_clock(str(source.get("arrival_iso") or ""))
    departure = _parse_clock(str(source.get("departure_iso") or ""))
    if arrival:
        moments.append(arrival)
    if departure:
        moments.append(departure)
    if not moments:
        milestone = _milestone_in_payload(data)
        moments = [moment for _kind, moment in _labeled_moments(milestone)]
        if arrival is None:
            arrival = next((moment for kind, moment in _labeled_moments(milestone) if kind == "arrival"), None)
        if departure is None:
            departure = _primary_moment(milestone)
    return moments, arrival, departure


def _date_allowance(known: str) -> tuple[set[str], set[int], set[str], Optional[dt.datetime]]:
    """Years, months and civil dates injected from /schedule for this stop or leg."""
    moments, arrival, _departure = _schedule_moments(known)
    years = {str(moment.year) for moment in moments}
    months = {moment.month for moment in moments}
    days = {moment.date().isoformat() for moment in moments}
    return years, months, days, arrival or (moments[0] if moments else None)


def _month_in_phrase(phrase: str) -> Optional[int]:
    for name, number in _MONTH_INDEX.items():
        if name and re.search(rf"\b{re.escape(name)}\b", phrase or "", re.IGNORECASE):
            return number
    return None


def _civil_day(phrase: str) -> Optional[str]:
    """YYYY-MM-DD when the phrase names a day, else nothing."""
    iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", phrase or "")
    if iso:
        return f"{iso.group(1)}-{iso.group(2)}-{iso.group(3)}"
    month = _month_in_phrase(phrase)
    day_match = re.search(r"\b(\d{1,2})(?:er)?\b", phrase or "")
    year_match = re.search(r"\b(1[89]\d{2}|20\d{2})\b", phrase or "")
    if month and day_match and year_match:
        day = int(day_match.group(1))
        if 1 <= day <= 31:
            return f"{year_match.group(0)}-{month:02d}-{day:02d}"
    return None


def _phrase_allowed(phrase: str, years: set[str], months: set[int], days: set[str]) -> bool:
    civil = _civil_day(phrase)
    if civil:
        return civil in days
    if _month_in_phrase(phrase) is not None:
        return False
    year_match = re.search(r"\b(1[89]\d{2}|20\d{2})\b", phrase or "")
    if year_match:
        return year_match.group(0) in years
    return False


def _spoken_date(moment: dt.datetime, lang: str) -> str:
    return arrival_phrase({"facts": {"arrival_iso": moment.date().isoformat()}}, lang)


def _drop_date_sentences(text: str) -> str:
    """Price replies keep the one code date sentence, not a model date."""
    kept = [
        sentence
        for sentence in _split_sentences(text or "")
        if sentence.strip() and not _DATE_PHRASE.search(sentence)
    ]
    return " ".join(kept).strip()


def _code_dates_sentence(milestone_id: str, lang: str) -> str:
    """One schedule sentence. A leg is a range. A stopover is arrival and departure."""
    block = _schedule_slice(milestone_id)
    departure = str(block.get("departure_iso") or "")[:10]
    arrival = str(block.get("arrival_iso") or "")[:10]
    is_leg = str(milestone_id or "").startswith("leg-")
    if is_leg and departure and arrival and departure <= arrival:
        if lang == "en":
            return f"Schedule dates: {departure} -> {arrival}."
        return f"Dates de l'étape : {departure} -> {arrival}."
    if arrival and departure:
        if lang == "en":
            return f"Arrival {arrival}, departure {departure}."
        return f"Arrivée {arrival}, départ {departure}."
    day = arrival or departure
    if not day:
        return ""
    if lang == "en":
        return f"The schedule date is {day}."
    return f"La date de l'escale est {day}."


def _drop_inverted_ranges(text: str) -> str:
    """Drop a sentence whose last ISO date is earlier than its first."""
    kept: list[str] = []
    for sentence in _split_sentences(text or ""):
        found = re.findall(r"\d{4}-\d{2}-\d{2}", sentence)
        if len(found) >= 2 and found[-1] < found[0]:
            continue
        year = re.search(r"\b(1[89]\d{2}|20\d{2})\b", sentence)
        if year and int(year.group(0)) < 2026:
            continue
        kept.append(sentence)
    return " ".join(kept).strip()


_ARRIVAL_CUE = re.compile(r"\barriv|\breach", re.IGNORECASE)
_DEPARTURE_CUE = re.compile(
    r"\bdepart|\bd[ée]part|\bleav|\bpartons\b|\bquitt",
    re.IGNORECASE,
)


def _ground_schedule_dates(text: str, known: str, lang: str = "") -> str:
    """Keep a date only when its day is one injected from /schedule.

    Any other day or year is replaced by the schedule arrival, or by the
    schedule departure when the sentence is about leaving. The model cannot
    swap 12 November and 29 November: only the injected day is kept.
    """
    years, _months, days, _primary = _date_allowance(known)
    _moments, arrival, departure = _schedule_moments(known)
    if not days and arrival is None and departure is None:
        return text or ""
    spoken_lang = "en" if lang == "en" else "fr"

    def replace(match: re.Match) -> str:
        phrase = match.group(0)
        if _phrase_allowed(phrase, years, set(), days):
            return phrase
        window = (text or "")[max(0, match.start() - 60):match.end() + 40]
        if _DEPARTURE_CUE.search(window) and not _ARRIVAL_CUE.search(window) and departure:
            return _spoken_date(departure, spoken_lang)
        if arrival:
            return _spoken_date(arrival, spoken_lang)
        if departure:
            return _spoken_date(departure, spoken_lang)
        return ""

    return re.sub(r"[ \t]{2,}", " ", _DATE_PHRASE.sub(replace, text or "")).strip()


def _drop_broken_fragments(text: str) -> str:
    """Drop a stub such as ``As the,`` and a sentence made only of function words."""

    def lead(match: re.Match) -> str:
        words = re.findall(r"[A-Za-zÀ-ÿ]+", match.group(1))
        if words and all(word.casefold() in _DANGLING_WORD for word in words):
            return ""
        return match.group(0)

    cleaned = _BROKEN_LEAD.sub(lead, text or "")
    kept: list[str] = []
    for sentence in _split_sentences(cleaned):
        words = _sentence_words(sentence)
        if not words or all(word.casefold() in _DANGLING_WORD for word in words):
            continue
        kept.append(sentence.strip())
    return " ".join(kept).strip()


def _with_schedule_numbers(facts: Any, known: str) -> Any:
    """Let the number filter keep the day and the year of a real schedule date."""
    _years, _months, days, _primary = _date_allowance(known)
    if isinstance(facts, dict):
        bag = dict(facts)
    else:
        bag = {"facts": facts}
    bag["schedule_dates"] = sorted(days)
    return bag


_INVENTED_FACT = re.compile(
    r"traditions?|shared meal|repas partag|infrastructures? modernes|"
    r"point de départ privilégié|privileged departure",
    re.IGNORECASE,
)


def _sentence_has_claim(sentence: str) -> bool:
    """A verb or a noun, not only a month, a year, or a function word."""
    for word in _sentence_words(sentence):
        if word.isdigit() or word.casefold() in _DANGLING_WORD:
            continue
        if word.casefold() in _MONTH_INDEX:
            continue
        return True
    return False


def _without_gaps(text: str, known: str, lang: str = "") -> str:
    """Drop a gap ([?], a unit with no number, an unknown date, an invented fact)."""
    years, months, _days, _primary = _date_allowance(known)
    grounded = _drop_broken_fragments(_ground_schedule_dates(text or "", known, lang))
    kept: list[str] = []
    for sentence in _split_sentences(grounded):
        piece = sentence.strip()
        if not piece or _INVENTED_FACT.search(piece):
            continue
        if "[?]" in piece:
            piece = re.sub(r"\s+", " ", piece.replace("[?]", " ")).strip(" ,;:")
            if not piece or not _sentence_has_claim(piece):
                continue
        if _BARE_UNIT.search(piece) and not re.search(r"\d", piece):
            continue
        if not _sentence_has_claim(piece):
            continue
        month_number = None
        for name, number in _MONTH_INDEX.items():
            if name in {"may", "mai"}:
                continue
            if re.search(rf"\b{re.escape(name)}\b", piece, re.IGNORECASE):
                month_number = number
                break
        if month_number is not None and month_number not in months:
            continue
        year_match = re.search(r"\b(1[89]\d{2}|20\d{2})\b", piece)
        if year_match and year_match.group(0) not in years:
            continue
        kept.append(piece)
    return " ".join(kept).strip()


def _source_of(raw: Any, text: str) -> dict[str, Any]:
    """Provider and model from the cascade. A bare string has no model id.

    ``reason`` is copied when the hop explains a fallback or a refused model id.
    ``fallback_reason`` is the status or exception class of each earlier hop.
    """
    provider = getattr(raw, "provider", None)
    model = getattr(raw, "model", None)
    if isinstance(provider, str) and provider.strip():
        source: dict[str, Any] = {"provider": provider.strip(), "model": str(model or "").strip()}
        reason = getattr(raw, "reason", "") or ""
        if isinstance(reason, str) and reason.strip():
            source["reason"] = reason.strip()
        fallback = getattr(raw, "fallback_reason", None)
        if isinstance(fallback, dict) and fallback:
            source["fallback_reason"] = {
                str(key): str(value) for key, value in fallback.items() if str(value).strip()
            }
        return source
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
            _with_known_facts(prompt),
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
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


def _pending_authorization(pledge: dict) -> dict:
    """One authorized or vaulted pledge, as the treasurer review lists it."""
    return {
        "pledge_id": pledge.get("_id"),
        "authorization_id": pledge.get("authorization_id"),
        "status": pledge.get("status"),
        "amount_eur": pledge.get("amount_eur"),
        "currency": pledge.get("currency") or "EUR",
        "description": pledge.get("description"),
        "kind": pledge.get("kind"),
        "target_id": pledge.get("target_id"),
        "milestone_id": pledge.get("milestone_id") or "",
        "authorization_expires_at": pledge.get("authorization_expires_at"),
        "authorization_age_days": authorization_age_days(pledge),
    }


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


def _verdict_system(lang: str) -> str:
    """JSON verdict instructions in the report language."""
    if lang == "en":
        return (
            "Reply with one JSON object only. No markdown fence and no commentary. "
            "Write reason in English. proposal is capture, void, wait or reauthorize. "
            "Do not invent a figure or a fact. reason may only use the JSON. "
            "Do not write [?] or a unit such as nm without its number."
        )
    return (
        "Réponds par un seul objet JSON. Pas de balise markdown et pas de commentaire. "
        "Écris reason en français. proposal vaut capture, void, wait ou reauthorize. "
        "N'invente aucun chiffre ni aucun fait. reason n'utilise que le JSON. "
        "N'écris pas [?] ni une unité comme nm sans son nombre."
    )


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
    prompt = _with_known_facts(json.dumps(payload, ensure_ascii=False, default=str))
    verdict_lang = "en" if str(allowed.get("language") or "") == "en" else "fr"
    try:
        parsed = await llm.ask_json(
            prompt,
            system=_verdict_system(verdict_lang),
            max_tokens=180,
            temperature=0,
        )
    except Exception:
        return None
    data = parsed.data if isinstance(getattr(parsed, "data", None), dict) else {}
    reason = _without_gaps(str(data.get("reason") or ""), prompt)
    data = {**data, "reason": reason}
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
    from .naviguide_bridge import resolve_milestone

    report_lang = _forced_lang(lang) or "fr"
    canonical = resolve_milestone(milestone_id) or milestone_id
    milestone = await get_milestone(milestone_id)
    if not latest_evidence(milestone):
        alt = await get_milestone(canonical)
        if alt:
            milestone = alt
    evidence = latest_evidence(milestone)
    met = evidence.get("met") if evidence else None
    reached = met is True
    decision = decision_for_evidence(evidence, milestone)
    related = await pledges_for_milestone(canonical)
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
    known = _with_known_facts(prompt)
    usable, source, report_lang = await _narrative_for_language(
        prompt, milestone_id, _forced_lang(lang), reached,
    )
    if usable:
        usable = _without_gaps(usable, known, report_lang)
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
    narrative = _without_unknown_marks(
        _without_jalon(
            filter_numbers(narrative, _with_schedule_numbers(allowed, known), lang=report_lang),
            report_lang,
        )
    )
    if report_lang == "fr":
        narrative = _standardise_french(narrative)
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
    pending = [_pending_authorization(pledge) for pledge in concerned]
    proposal = {
        "milestone_id": milestone_id,
        "proposal": decision,
        "report": narrative,
        "justification": justification,
        "pledge_ids": [row["pledge_id"] for row in pending],
        "pending_authorizations": pending,
        "paypal_tool_calls": list(getattr(reader, "call_log", []) or []),
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


def _is_fund_question(message: str) -> bool:
    """A fund question, not a gift. A priced line stays a pledge.

    ``How much money is in the project fund?`` names the project fund.
    ``fonds commun`` and ``caisse`` stay the other fund questions.
    ``Combien … escale``, ``promis`` with a stop, and ``pledged`` ask what
    was promised. They are not a one-mile pledge.
    """
    text = message or ""
    money_in_a_fund = bool(
        re.search(r"\bhow\s+much\s+money\b", text, re.IGNORECASE)
        and re.search(r"\bfunds?\b", text, re.IGNORECASE)
    )
    names_stop = bool(re.search(r"\bescales?\b", text, re.IGNORECASE)) or _place(text) is not None
    combien_escale = bool(re.search(r"\bcombien\b", text, re.IGNORECASE)) and names_stop
    promised_escale = bool(re.search(r"\bpromis\b", text, re.IGNORECASE)) and names_stop
    pledged = bool(re.search(r"\bpledged\b", text, re.IGNORECASE))
    topical = (
        _COMMON_FUND.search(text)
        or _PROJECT_FUND.search(text)
        or re.search(r"\bcaisse\b", text, re.IGNORECASE)
        or money_in_a_fund
        or combien_escale
        or promised_escale
        or pledged
    )
    if not topical:
        return False
    return not _message_prices_a_pledge(text)


def _fund_system(lang: str) -> str:
    language = "English" if lang == "en" else "French"
    return (
        f"You are the Blue Intelligence Escales captain. Reply in {language}. "
        "Answer the common-fund question from the fund JSON only. "
        "Repeat income_eur, spending_eur and balance_eur. Do not invent a figure. "
        "Do not propose to take or release money. Do not create an order. "
        "One or two complete sentences. At most 80 words."
    )


def _fund_place_label(milestone_id: str, lang: str) -> str:
    """Name the fund the figures come from. A stopover is its own caisse."""
    token = (milestone_id or "").strip().casefold()
    if token in {"projet", "project", "project_pledge", "project-pledge"}:
        return "the project fund" if lang == "en" else "la caisse du projet"
    if token in {"fonds-commun", "fund", "common-fund", "common_fund", "caisse"}:
        return "the common fund" if lang == "en" else "le fonds commun"
    shown = display_name(milestone_id)
    if lang == "en":
        return f"the fund at {shown}" if shown else "the fund"
    return f"la caisse de {shown}" if shown else "la caisse"


def _fund_rules_text(fund: dict, lang: str) -> str:
    """Rules sentence. Every figure comes from the fund route."""
    if fund.get("missing"):
        if lang == "en":
            return "I have no figures for that fund."
        return "Je n'ai pas les chiffres de cette caisse."
    label = _fund_place_label(str(fund.get("milestone_id") or ""), lang)
    income = format_amount(fund.get("income_eur") or "0.00", lang)
    spending = format_amount(fund.get("spending_eur") or "0.00", lang)
    balance = format_amount(fund.get("balance_eur") or "0.00", lang)
    if lang == "en":
        return f"For {label}, income is {income}, spending is {spending}, and the balance is {balance}."
    return f"Pour {label}, les recettes sont {income}, les dépenses sont {spending}, et le solde est {balance}."


def _keeps_fund_figures(text: str, fund: dict) -> bool:
    if fund.get("missing"):
        return bool((text or "").strip())
    return all(
        amount_in_text(text, str(fund.get(key) or "0.00"))
        for key in ("income_eur", "spending_eur", "balance_eur")
    )


async def _fund_for_question(message: str) -> dict:
    """The same payload as GET /milestones/{id}/fund."""
    from .ledger import fund_for_milestone
    from .naviguide_bridge import resolve_milestone

    text = message or ""
    if _PROJECT_FUND.search(text):
        milestone_id = "projet"
    else:
        place = resolve_milestone(text)
        if place and str(place).startswith("leg-"):
            place = None
        milestone_id = place or "fonds-commun"
    try:
        return await fund_for_milestone(milestone_id)
    except LookupError:
        return {"milestone_id": milestone_id, "missing": True, "currency": "EUR"}


def _compose_fund_reply(prose: str, lang: str) -> str:
    rules = _public_rule(lang)
    reply = _fit_words(_strip_signatures(prose or ""), [rules, _signature(lang)])
    if lang == "fr":
        reply = _standardise_french(reply)
    return reply


def _hidden_fund_reply(lang: str) -> str:
    """Project and boat-fund totals stay with the treasurer."""
    if lang == "en":
        return "Only the treasurer can see this fund's totals."
    return "Seul le trésorier peut voir les totaux de cette caisse."


async def _answer_fund(
    message: str, lang: str, *, treasurer: bool = False,
) -> tuple[str, dict[str, str], Optional[dict]]:
    """NIM only when its flag is on. The rules sentence is the fallback.

    A stopover fund is public. The project fund and the boat's common fund
    are the same totals as the treasurer routes: without a valid key the
    reply names no amount and the payload is empty.
    """
    from .ledger import _unplaced_bucket

    fund = await _fund_for_question(message)
    if _unplaced_bucket(str(fund.get("milestone_id") or "")) and not treasurer:
        reply = _compose_fund_reply(_hidden_fund_reply(lang), lang)
        return reply, _rules_source(), None
    public = None if fund.get("missing") else fund
    allowed = {"fund": public or fund, "message": message}
    rules = _fund_rules_text(fund, lang)
    raw, source = "", _rules_source()
    if public is not None:
        prompt = json.dumps({"fund": public, "message": message}, ensure_ascii=False, default=str)
        raw, source = await _llm_text(
            prompt,
            _fund_system(lang),
            max_tokens=_CHAT_MAX_TOKENS,
            temperature=_CHAT_TEMPERATURE,
        )
    prose = ""
    if raw and not _CHARGE_CLAIM.search(raw):
        if lang == "fr":
            raw = _french_labels(raw)
        filtered = filter_numbers(raw, allowed, lang=lang)
        if "[?]" not in filtered and _keeps_fund_figures(filtered, fund):
            prose = filtered
        else:
            source = _rules_source()
    if not prose:
        prose = filter_numbers(rules, allowed, lang=lang)
        source = _rules_source()
    reply = _compose_fund_reply(prose, lang)
    if not _keeps_fund_figures(reply, fund):
        reply = _compose_fund_reply(filter_numbers(rules, allowed, lang=lang), lang)
        source = _rules_source()
    return reply, source, public


def _is_cabin_price_question(message: str) -> bool:
    """A catalogue price, not a fund total. ``How much is a cabin?`` is one."""
    text = message or ""
    if _is_fund_question(text):
        return False
    if not re.search(
        r"\bhow\s+much\b|\bcombien\b|\bprix\b|\bprices?\b|\bcosts?\b|\bco[uû]te",
        text,
        re.IGNORECASE,
    ):
        return False
    return _sum_quantity(_CABIN_COUNT, text) > 0


def _cabin_price_reply(lang: str) -> str:
    unit = _SIMULATED_EUR["cabin_leg"].quantize(Decimal("0.01"))
    shown = f"{unit:.2f}".rstrip("0").rstrip(".")
    if lang == "en":
        prose = f"A cabin is {shown} € per leg."
    else:
        prose = f"Une cabine coûte {shown} € par jambe."
    return _fit_words("", [prose, _signature(lang)])


_PAYPAL_READONLY = re.compile(
    r"\b(?:list|show|search|check)\s+(?:paypal\s+)?(?:transactions?|disputes?|invoices?)\b",
    re.IGNORECASE,
)


def _is_paypal_readonly_question(message: str) -> bool:
    text = message or ""
    if _PAYPAL_READONLY.search(text):
        return True
    if re.search(
        r"\bpaypal\s+(?:transaction|dispute)\s+(?:search|list)\b",
        text,
        re.I,
    ):
        return True
    if re.search(
        r"\b(?:tr[ée]sorier|treasurer)\b.*\b(?:transaction|dispute|invoice)s?\b",
        text,
        re.I,
    ):
        return True
    return False


def _paypal_search_window() -> tuple[str, str]:
    return default_transaction_search_window()


def _paypal_readonly_reply(message: str, lang: str, reader: ReadOnlyTools) -> Optional[str]:
    if not _is_paypal_readonly_question(message):
        return None
    try:
        if re.search(r"\bdisputes?\b", message, re.I):
            payload = reader.get("disputes.list")
            items = payload.get("items") if isinstance(payload, dict) else []
            count = len(items or [])
            if lang == "en":
                return f"PayPal disputes (read-only): {count} open item(s)."
            return f"Litiges PayPal (lecture seule) : {count} dossier(s)."
        if re.search(r"\btransactions?\b", message, re.I):
            start, end = _paypal_search_window()
            payload = reader.get("transactions.search", f"{start}|{end}")
            details = payload.get("transaction_details") if isinstance(payload, dict) else []
            count = len(details or [])
            if lang == "en":
                return (
                    f"PayPal transactions from {start[:10]} to {end[:10]} (read-only): "
                    f"{count} row(s)."
                )
            return (
                f"Transactions PayPal du {start[:10]} au {end[:10]} (lecture seule) : "
                f"{count} ligne(s)."
            )
        if re.search(r"\binvoices?\b", message, re.I):
            payload = reader.get("invoices.list", "1")
            items = payload.get("items") if isinstance(payload, dict) else []
            count = len(items or [])
            if lang == "en":
                return f"PayPal invoices (read-only): {count} item(s)."
            return f"Factures PayPal (lecture seule) : {count} élément(s)."
    except Exception as exc:
        detail = str(exc)[:120]
        if lang == "en":
            return f"PayPal read-only lookup failed: {detail}"
        return f"Échec de la lecture PayPal (lecture seule) : {detail}"
    return None


async def chat(
    message: str,
    *,
    treasurer: bool = False,
    lang: Optional[str] = None,
    accept_language: str = "",
    reader: Optional[ReadOnlyTools] = None,
) -> dict:
    """Help a contributor phrase a pledge and offer the HelloAsso membership URL.

    ``treasurer`` is true only when the request carried a valid ``x-admin-key``.
    ``lang`` is the app language. It wins over Accept-Language and the message.
    """
    text = (message or "").strip()
    if not text:
        raise ValueError("message is required")
    url = membership_url()
    lang = resolve_chat_lang(text, lang, accept_language)
    if treasurer and reader is not None:
        tool_reply = _paypal_readonly_reply(text, lang, reader)
        if tool_reply:
            return {
                "reply": _fit_words("", [tool_reply, _signature(lang)]),
                "membership_url": url,
                "suggested_pledge": None,
                "cart": None,
                "model_source": "paypal_readonly_tools",
                "fund": None,
                "paypal_tools": list(reader.allowed()),
            }
    if _is_capture_rule_question(text):
        return {
            "reply": _capture_rule_reply(lang),
            "membership_url": url,
            "suggested_pledge": None,
            "cart": None,
            "model_source": _rules_source(),
            "fund": None,
        }
    if _is_fund_question(text):
        reply, source, fund = await _answer_fund(text, lang, treasurer=treasurer)
        return {
            "reply": reply,
            "membership_url": url,
            "suggested_pledge": None,
            "cart": None,
            "model_source": source,
            "fund": fund,
        }
    if _is_cabin_price_question(text):
        suggested = suggest_pledge(text, lang)
        milestone = str((suggested or {}).get("milestone_id") or "")
        if not milestone.startswith("leg-"):
            if lang == "en":
                prose = "Which stopover? Name the stop and I will compute the pledge."
            else:
                prose = "Quelle escale ? Indiquez son nom pour que je calcule la promesse."
            return {
                "reply": _fit_words("", [prose, _signature(lang)]),
                "membership_url": url,
                "suggested_pledge": None,
                "cart": None,
                "model_source": _rules_source(),
                "fund": None,
            }
        reply = _compose_chat_reply("", suggested, url, lang, treasurer=False, ask_escale=False)
        return {
            "reply": reply,
            "membership_url": url,
            "suggested_pledge": suggested,
            "cart": pledge_cart(text, lang, suggested),
            "model_source": _rules_source(),
            "fund": None,
        }
    treasurer = _is_treasurer_question(text)
    suggested = suggest_pledge(text, lang)
    cart = pledge_cart(text, lang, suggested)
    ask_escale = suggested is None and not treasurer and not _is_status_question(text)
    allowed = {"message": text, "suggested": suggested, "membership_url": url}
    if suggested is None:
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
            elif lang == "en":
                raw = _english_labels(raw)
            known = _with_known_facts(prompt)
            raw = _drop_inverted_ranges(raw)
            raw = _ground_schedule_dates(raw, known, lang)
            raw = filter_numbers(raw, _with_schedule_numbers(allowed, known), lang=lang)
            raw = _without_gaps(raw, known, lang)
        else:
            raw, source = "", _rules_source()
    reply = _compose_chat_reply(
        raw or "", suggested, url, lang, treasurer=treasurer, ask_escale=ask_escale,
    )
    return {
        "reply": reply,
        "membership_url": url,
        "suggested_pledge": suggested,
        "cart": cart,
        "model_source": source,
    }


# Kinds other than mile and meal. Same catalogue as ``_SIMULATED_EUR`` /
# ``simulated_unit``. A project pledge and the common fund stay free-amount:
# the line exists only when the visitor writes the euros.
_BERTH_COUNT = re.compile(
    r"\b(?:(\d+(?:[.,]\d+)?)\s+)?(?:berths?|postes?|mouillages?|places?\s+de\s+port)\b",
    re.IGNORECASE,
)
_NIGHT_COUNT = re.compile(
    r"\b(?:(\d+(?:[.,]\d+)?)\s+)?(?:nights?|nuits?)\b",
    re.IGNORECASE,
)
_CARE_COUNT = re.compile(
    r"\b(?:(\d+(?:[.,]\d+)?)\s+)?(?:cares?|soins?|elsa)\b",
    re.IGNORECASE,
)
_CABIN_COUNT = re.compile(
    r"\b(?:(\d+(?:[.,]\d+)?)\s+)?(?:cabines?|cabins?|cabin\s+legs?|boat-stops?)\b",
    re.IGNORECASE,
)
_PROJECT_PLEDGE = re.compile(
    r"\bpour\s+le\s+projets?\b|\bau\s+projets?\b|\b(?:promesse\s+)?projets?\b"
    r"|\bfor\s+the\s+project\b|\btowards?\s+the\s+project\b|\bto\s+the\s+project\b"
    r"|\bproject\s+pledges?\b",
    re.IGNORECASE,
)
# « cette nuit » et « tonight » sont un moment, pas une nuit à bord.
_NOT_A_NIGHT = re.compile(r"\bcette\s+nuit\b|\btonight\b", re.IGNORECASE)
_WRITTEN_NUMBERS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "un": "1", "deux": "2", "trois": "3", "quatre": "4", "cinq": "5",
    "sept": "7", "huit": "8", "neuf": "9", "dix": "10",
}
_WRITTEN_NUMBER = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|un|deux|trois|quatre|cinq|sept|huit|neuf|dix)\b",
    re.IGNORECASE,
)
_DINNER_COUNT = re.compile(
    r"\b(?:(\d+(?:[.,]\d+)?)\s+)?(?:d[iî]ners?|dinners?)\b",
    re.IGNORECASE,
)
_COMMON_FUND = re.compile(
    r"\bfonds?\s+commun\b|\bcommon\s+funds?\b",
    re.IGNORECASE,
)
_PROJECT_FUND = re.compile(
    r"\bproject\s+funds?\b|\bfonds?\s+(?:du|des|au)\s+projets?\b|\bcaisse\s+du\s+projet\b",
    re.IGNORECASE,
)
_EUR_AMOUNT = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:€|eur\b|euros?\b)",
    re.IGNORECASE,
)
_KIND_WORDS = {
    "berth": (("poste", "postes"), ("berth", "berths")),
    "night": (("nuit", "nuits"), ("night", "nights")),
    "care": (("soin", "soins"), ("care", "cares")),
    "cabin_leg": (("cabine", "cabines"), ("cabin leg", "cabin legs")),
    "project_pledge": (("promesse projet", "promesse projet"), ("project pledge", "project pledge")),
    "common_fund": (("fonds commun", "fonds commun"), ("common fund", "common fund")),
}


def _with_written_numbers(text: str) -> str:
    """``deux`` et ``two`` deviennent ``2``. Un à dix, one à ten."""

    def repl(match: re.Match) -> str:
        return _WRITTEN_NUMBERS[match.group(1).casefold()]

    return _WRITTEN_NUMBER.sub(repl, text or "")


def _explicit_miles(text: str) -> Decimal:
    total = Decimal("0")
    for match in _MILES.finditer(_with_written_numbers(text)):
        try:
            count = Decimal(match.group(1).replace(",", "."))
        except InvalidOperation:
            continue
        if count > 0:
            total += count
    return total


def _explicit_dinners(text: str) -> int:
    total = _sum_quantity(_DINNER_COUNT, text)
    if total == total.to_integral_value():
        return int(total)
    return int(total.to_integral_value())


def _night_quantity(text: str) -> Decimal:
    """Une nuit commandée. « cette nuit » et « tonight » ne comptent pas."""
    cleaned = _NOT_A_NIGHT.sub(" ", text or "")
    return _sum_quantity(_NIGHT_COUNT, cleaned)


def _sum_quantity(pattern: re.Pattern, text: str) -> Decimal:
    total = Decimal("0")
    for match in pattern.finditer(_with_written_numbers(text)):
        raw = match.group(1)
        if not raw:
            total += 1
            continue
        try:
            qty = Decimal(raw.replace(",", "."))
        except InvalidOperation:
            continue
        if qty > 0:
            total += qty
    return total


def _amount_near(text: str, pattern: re.Pattern) -> Optional[Decimal]:
    match = pattern.search(text or "")
    if not match:
        return None
    start = max(0, match.start() - 48)
    end = min(len(text), match.end() + 48)
    found = _EUR_AMOUNT.search(_with_written_numbers(text[start:end]))
    if not found:
        return None
    try:
        amount = Decimal(found.group(1).replace(",", "."))
    except InvalidOperation:
        return None
    if amount <= 0:
        return None
    return amount.quantize(Decimal("0.01"))


def _kind_description(kind: str, quantity: Decimal, lang: str) -> str:
    french, english = _KIND_WORDS[kind]
    pair = english if lang == "en" else french
    noun = pair[0] if quantity == 1 else pair[1]
    if kind in {"project_pledge", "common_fund"}:
        return noun
    return f"{_format_count(quantity)} {noun}"


def _join_desc(lines: list[dict], lang: str) -> str:
    parts = [str(line.get("description") or "") for line in lines if line.get("description")]
    if not parts:
        return ""
    if lang == "en":
        return " and ".join(parts)
    return " et ".join(parts)


def _cart_line(
    kind: str,
    quantity: Decimal,
    place: str,
    lang: str,
    amount: Optional[Decimal],
    description: str,
) -> dict:
    """One cart row. Copies ``simulated_unit`` and keeps AUTHORIZE."""
    row = simulated_unit(kind)
    row.update(
        {
            "quantity": _format_count(quantity),
            "description": description,
            "milestone_id": place,
            "target_id": place,
            "intent": "AUTHORIZE",
            "price_label": SIMULATED_PRICE_LABEL,
        }
    )
    if amount is not None:
        shown = f"{amount.quantize(Decimal('0.01')):.2f}"
        row["amount_eur"] = shown
        # Same body as POST /api/escales/pledges, which creates the AUTHORIZE order.
        row["pledge"] = {
            "amount_eur": shown,
            "description": description,
            "milestone_id": place,
            "kind": kind,
            "target_id": place,
        }
    return row


def _fixed_line(kind: str, quantity: Decimal, place: str, lang: str) -> dict:
    unit = _SIMULATED_EUR[kind]
    amount = (quantity * unit).quantize(Decimal("0.01"))
    if kind == "mile":
        description = _miles_description(quantity, lang)
    elif kind == "meal":
        description = _dinner_description(int(quantity), lang)
    else:
        description = _kind_description(kind, quantity, lang)
    return _cart_line(kind, quantity, place, lang, amount, description)


def _chosen_line(kind: str, place: str, lang: str, amount: Decimal) -> dict:
    return _cart_line(
        kind,
        Decimal("1"),
        place,
        lang,
        amount,
        _kind_description(kind, Decimal("1"), lang),
    )


def _catalogue_lines(text: str, lang: str, place: str) -> list[dict]:
    """Miles and meals first, then the other priced kinds, in catalogue order."""
    lines: list[dict] = []
    miles = _explicit_miles(text)
    dinners = _explicit_dinners(text)
    if miles > 0:
        lines.append(_fixed_line("mile", miles, place, lang))
    if dinners > 0:
        lines.append(_fixed_line("meal", Decimal(dinners), place, lang))
    for kind, pattern in (
        ("berth", _BERTH_COUNT),
        ("night", _NIGHT_COUNT),
        ("care", _CARE_COUNT),
        ("cabin_leg", _CABIN_COUNT),
    ):
        quantity = _night_quantity(text) if kind == "night" else _sum_quantity(pattern, text)
        if quantity > 0:
            line_place = place
            if kind == "cabin_leg":
                line_place = _cabin_milestone(text, place)
            lines.append(_fixed_line(kind, quantity, line_place, lang))
    for kind, pattern in (
        ("project_pledge", _PROJECT_PLEDGE),
        ("common_fund", _COMMON_FUND),
    ):
        amount = _amount_near(text, pattern)
        if amount is not None:
            lines.append(_chosen_line(kind, place, lang, amount))
    if not lines:
        lines.append(_fixed_line("mile", Decimal("1"), place, lang))
    return lines


_PORT_LOCAL_TZ = {
    "dakar": ZoneInfo("Africa/Dakar"),
    "lorient": ZoneInfo("Europe/Paris"),
    "pointe-a-pitre": ZoneInfo("America/Guadeloupe"),
    "pointe-a-pitre-guadeloupe": ZoneInfo("America/Guadeloupe"),
}


def _local_eta(place: str, stop: Optional[dict]) -> Optional[str]:
    """Arrival in the port's local time for Dakar, Lorient and Pointe-à-Pitre.

    Other stopovers keep the stored ``arrival_iso``.
    """
    if not stop:
        return None
    raw = stop.get("arrival_iso")
    if not raw:
        return None
    text = str(raw).strip()
    slug = _escale_slug(place)
    zone = _PORT_LOCAL_TZ.get(slug)
    if zone is None and slug.endswith("-guadeloupe"):
        zone = _PORT_LOCAL_TZ["pointe-a-pitre"]
    if zone is None:
        return text
    parsed = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        moment = dt.datetime.fromisoformat(parsed)
    except ValueError:
        return text
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.astimezone(zone).replace(microsecond=0).isoformat()


def _schedule_stop(place: str) -> Optional[dict]:
    """Arrival already stored on the local schedule. No partner call."""
    from .naviguide_bridge import local_schedule_export, resolve_milestone

    canonical = resolve_milestone(place)
    if not canonical:
        return None
    for item in local_schedule_export().get("escales") or []:
        if isinstance(item, dict) and item.get("milestone_id") == canonical:
            return item
    return None


def pledge_cart(message: str, lang: str, suggested: Optional[dict]) -> Optional[dict]:
    """Multi-line cart for the same AUTHORIZE total. No PayPal order.

    ``eta`` is the schedule arrival. Dakar, Lorient and Pointe-à-Pitre are
    shown in local time. ``clock_start`` is the voyage clock. ``available``
    is the schedule flag for that stopover.
    """
    if not suggested:
        return None
    from .config import clock_start

    text = message or ""
    place = str(suggested.get("milestone_id") or "")
    lines = _catalogue_lines(text, lang, place)
    had_named = _explicit_miles(text) > 0 or _explicit_dinners(text) > 0
    extras = [line for line in lines if line["kind"] not in {"mile", "meal"}]
    if extras and not had_named:
        lines = extras
    stop = _schedule_stop(place)
    return {
        "lines": lines,
        "amount_eur": suggested.get("amount_eur"),
        "currency": "EUR",
        "description": suggested.get("description"),
        "milestone_id": place,
        "target_id": place,
        "intent": "AUTHORIZE",
        "clock_start": clock_start(),
        "eta": _local_eta(place, stop),
        "available": bool(stop and stop.get("flag")),
        "simulated": True,
        "indicative": True,
        "price_label": SIMULATED_PRICE_LABEL,
    }


def _extend_pledge(base: dict, message: str, lang: str) -> dict:
    text = message or ""
    place = str(base.get("milestone_id") or "")
    lines = _catalogue_lines(text, lang, place)
    extras = [line for line in lines if line["kind"] not in {"mile", "meal"}]
    if not extras:
        return base
    had_named = _explicit_miles(text) > 0 or _explicit_dinners(text) > 0
    if had_named:
        priced = lines
        description = base.get("description") or ""
        extra = _join_desc(extras, lang)
        if extra:
            if lang == "en":
                description = f"{description} and {extra}"
            else:
                description = f"{description} et {extra[0].lower() + extra[1:]}"
        item = "mixed"
    else:
        priced = extras
        description = _join_desc(extras, lang)
        item = extras[0]["kind"] if len(extras) == 1 else "mixed"
    total = sum(
        (Decimal(str(line["amount_eur"])) for line in priced if line.get("amount_eur")),
        Decimal("0"),
    ).quantize(Decimal("0.01"))
    result = dict(base)
    result["amount_eur"] = f"{total:.2f}"
    result["description"] = description
    result["item"] = item
    if item == "mixed":
        result.pop("kind", None)
    else:
        result["kind"] = item
    return result


_suggest_pledge_miles = suggest_pledge


def _message_prices_a_pledge(message: str) -> bool:
    """True when the sentence already names a catalogue line with an amount."""
    text = message or ""
    if _amount_near(text, _PROJECT_PLEDGE) is not None:
        return True
    if _amount_near(text, _COMMON_FUND) is not None:
        return True
    if not _place(text):
        return False
    if _explicit_miles(text) > 0 or _explicit_dinners(text) > 0:
        return True
    if _night_quantity(text) > 0:
        return True
    return any(_sum_quantity(pattern, text) > 0 for pattern in (_BERTH_COUNT, _CARE_COUNT, _CABIN_COUNT))


def _cabin_milestone(message: str, place: str) -> str:
    """Direction wins over the first port named in the sentence."""
    from .naviguide_bridge import leg_by_id, leg_departing_from, leg_for_message

    directed = leg_for_message(message)
    if directed:
        return str(directed["id"])
    if place.startswith("leg-") and leg_by_id(place):
        return place
    leg = leg_departing_from(place)
    if leg:
        return str(leg["id"])
    return place


def _open_pledge(
    message: str,
    lang: str,
    pattern: re.Pattern,
    kind: str,
    description_fr: str,
    description_en: str,
    target_id: str,
) -> Optional[dict]:
    """Project and common-fund lines need no stopover. The milestone stays empty."""
    amount = _amount_near(message or "", pattern)
    if amount is None:
        return None
    return {
        "amount_eur": f"{amount:.2f}",
        "currency": "EUR",
        "description": description_en if lang == "en" else description_fr,
        "milestone_id": "",
        "target_id": target_id,
        "intent": "AUTHORIZE",
        "item": kind,
        "kind": kind,
        "simulated": True,
        "price_label": SIMULATED_PRICE_LABEL,
    }


def _project_pledge_alone(message: str, lang: str) -> Optional[dict]:
    """« Je donne 15 euros au projet » names no stopover and is still a project pledge."""
    return _open_pledge(
        message, lang, _PROJECT_PLEDGE, "project_pledge", "promesse projet", "project pledge", "projet",
    )


def _fund_pledge_alone(message: str, lang: str) -> Optional[dict]:
    """« 15 euros au fonds commun » without a port is still the common fund."""
    if _place(message or ""):
        return None
    return _open_pledge(
        message, lang, _COMMON_FUND, "common_fund", "fonds commun", "common fund", "fonds-commun",
    )


def _cabin_only(message: str) -> bool:
    """A cabin, and not also miles, a dinner, or another catalogue line."""
    text = message or ""
    if _sum_quantity(_CABIN_COUNT, text) <= 0:
        return False
    if _explicit_miles(text) > 0 or _explicit_dinners(text) > 0:
        return False
    if _night_quantity(text) > 0:
        return False
    if any(_sum_quantity(pattern, text) > 0 for pattern in (_BERTH_COUNT, _CARE_COUNT)):
        return False
    if _amount_near(text, _PROJECT_PLEDGE) is not None:
        return False
    if _amount_near(text, _COMMON_FUND) is not None:
        return False
    return True


def _cabin_pledge_alone(message: str, lang: str) -> Optional[dict]:
    """A cabin, with its leg when the sentence names one. Never one mile."""
    if _sum_quantity(_CABIN_COUNT, message or "") <= 0:
        return None
    milestone = _cabin_milestone(message, _place(message) or "")
    if not str(milestone).startswith("leg-"):
        milestone = ""
    quantity = _sum_quantity(_CABIN_COUNT, message or "")
    amount = (quantity * _SIMULATED_EUR["cabin_leg"]).quantize(Decimal("0.01"))
    description = _kind_description("cabin_leg", quantity, lang)
    return {
        "amount_eur": f"{amount:.2f}",
        "currency": "EUR",
        "description": description,
        "milestone_id": milestone,
        "target_id": milestone,
        "intent": "AUTHORIZE",
        "item": "cabin_leg",
        "kind": "cabin_leg",
        "simulated": True,
        "price_label": SIMULATED_PRICE_LABEL,
    }


def suggest_pledge(message: str, lang: str = "fr") -> Optional[dict]:
    """Mile and dinner pledge, plus the other catalogue lines in the same total.

    A cabin is not the one-mile default. The cabin line wins when the
    message names a cabin and no other catalogue amount.
    """
    if _cabin_only(message):
        cabin = _cabin_pledge_alone(message, lang)
        if cabin:
            return cabin
    base = _suggest_pledge_miles(message, lang)
    if not base:
        return (
            _cabin_pledge_alone(message, lang)
            or _project_pledge_alone(message, lang)
            or _fund_pledge_alone(message, lang)
        )
    resolved = _extend_pledge(base, message, lang)
    if resolved.get("kind") == "cabin_leg":
        resolved["milestone_id"] = _cabin_milestone(message, str(resolved.get("milestone_id") or ""))
    if resolved.get("kind") in {"project_pledge", "common_fund"} and not str(resolved.get("milestone_id") or ""):
        resolved["target_id"] = "projet" if resolved["kind"] == "project_pledge" else "fonds-commun"
    return resolved
