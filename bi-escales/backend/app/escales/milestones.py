"""Milestone evidence and the number filter.

NAVIGUIDE evidence posted through the API is flagged ``simulation``.
The decision (capture, void, or wait) comes from that evidence. A model
proposal is advisory. ``filter_numbers`` drops a figure that is neither in
the evidence nor the sum or difference of two figures that are.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
# A price token, with an optional euro marker. The marker must not eat the next word.
_AMOUNT_SPAN = re.compile(
    r"\d+(?:[.,]\d+)?(?:\s*(?:€|eur(?:os?)?))?(?!\w)",
    re.IGNORECASE,
)
_MONEY_KEY = re.compile(r"amount|prix|price|eur", re.IGNORECASE)


def allowed_numbers(facts: Any) -> set[str]:
    """Digits that already appear in the evidence (or the bag we pass in)."""
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, int):
            found.add(str(value))
            return
        if isinstance(value, float):
            found.add(str(value))
            found.add(f"{value:.2f}")
            if value.is_integer():
                found.add(str(int(value)))
            return
        if isinstance(value, str):
            found.update(_NUMBER.findall(value))
            return
        if isinstance(value, dict):
            for key, item in value.items():
                walk(key)
                walk(item)
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(facts)
    return found


def _as_decimal(token: str) -> Optional[Decimal]:
    """``120``, ``120.00`` and ``120,00`` are the same amount."""
    try:
        return Decimal(token.replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def amount_in_text(text: str, amount: str) -> bool:
    """True when ``text`` contains ``amount``, including a French decimal comma."""
    target = _as_decimal(str(amount))
    if target is None:
        return str(amount) in (text or "")
    return any(_as_decimal(token) == target for token in _NUMBER.findall(text or ""))


def format_amount(amount: Any, lang: str = "fr") -> str:
    """French uses a decimal comma and €. English uses a decimal point and EUR."""
    value = amount if isinstance(amount, Decimal) else _as_decimal(str(amount))
    if value is None:
        return str(amount)
    quantized = value.quantize(Decimal("0.01"))
    if lang == "en":
        return f"{quantized:.2f} EUR"
    return f"{quantized:.2f}".replace(".", ",") + " €"


def _money_values(facts: Any) -> set[Decimal]:
    """Amounts named as money. A mile count stored beside them is not money."""
    found: set[Decimal] = set()

    def walk(key: Any, value: Any) -> None:
        money_key = isinstance(key, str) and bool(_MONEY_KEY.search(key))
        if isinstance(value, bool):
            return
        if isinstance(value, Decimal):
            if money_key:
                found.add(value)
            return
        if isinstance(value, int):
            if money_key:
                found.add(Decimal(value))
            return
        if isinstance(value, float):
            if money_key:
                found.add(Decimal(str(value)))
            return
        if isinstance(value, str):
            if money_key:
                for token in _NUMBER.findall(value):
                    parsed = _as_decimal(token)
                    if parsed is not None:
                        found.add(parsed)
            return
        if isinstance(value, dict):
            for child_key, item in value.items():
                walk(child_key, item)
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                walk(key, item)

    walk("", facts)
    return found


def _with_derived(values: set[Decimal]) -> set[Decimal]:
    """Allow the sum and the absolute difference of two evidence figures."""
    extra = set(values)
    numbers = list(values)
    for index, left in enumerate(numbers):
        for right in numbers[index + 1:]:
            extra.add(left + right)
            extra.add(abs(left - right))
    return extra


def filter_numbers(text: str, facts: Any, lang: str = "fr") -> str:
    """Replace any figure that is not already present in ``facts``.

    ``120``, ``120.00`` and ``120,00`` are accepted as the same amount.
    A money amount is then written in the reply language: ``120,00 €`` in
    French, ``120.00 EUR`` in English. A derived figure such as ``170``
    from ``250`` and ``80`` is kept as a count.
    """
    allowed = allowed_numbers(facts)
    values = _with_derived(
        {item for item in (_as_decimal(token) for token in allowed) if item is not None}
    )
    money = _money_values(facts)

    def replace(match: re.Match) -> str:
        span = match.group(0)
        number = _NUMBER.match(span)
        if number is None:
            return span
        token = number.group(0)
        marked_as_money = bool(span[number.end():].strip())
        value = _as_decimal(token)
        if value is None or value not in values:
            return "[?]"
        has_decimal = "," in token or "." in token
        if marked_as_money or (has_decimal and value in money):
            return format_amount(value, lang)
        return token

    return _AMOUNT_SPAN.sub(replace, text or "")


# Slugs the captain hears, and the ids stored on the ledger.
_MILESTONE_ALIASES = {
    "mayotte": "dep-mayotte",
    "fort-de-france": "dep-fort-de-france",
    "fort de france": "dep-fort-de-france",
    "long-haul": "dep-long-haul",
    "transatlantique": "dep-long-haul",
}


def canonical_milestone_id(raw: str) -> str:
    """Map a spoken place onto the ledger id when one exists.

    ``mayotte`` becomes ``dep-mayotte``. An unknown place is left unchanged
    so a missing arrival date still refuses the pledge.
    """
    text = (raw or "").strip()
    key = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not key:
        return text
    if key in _MILESTONE_ALIASES:
        return _MILESTONE_ALIASES[key]
    bare = key[4:] if key.startswith("dep-") else key
    if bare in _MILESTONE_ALIASES:
        return _MILESTONE_ALIASES[bare]
    return key if key.startswith("dep-") else text


def decision_for(met: Optional[bool]) -> str:
    """Rules on facts. A model proposal does not change this."""
    if met is True:
        return "capture"
    if met is False:
        return "void"
    return "wait"


def simulation_evidence(met: Optional[bool], facts: Optional[dict]) -> dict:
    """Evidence record flagged simulation for NAVIGUIDE."""
    from .pledges import now_iso

    return {
        "flag": "simulation",
        "provider": "NAVIGUIDE",
        "source": "simulation",
        "met": met,
        "facts": dict(facts or {}),
        "recorded_at": now_iso(),
    }


async def record_evidence(milestone_id: str, met: Optional[bool], facts: Optional[dict]) -> dict:
    from . import evidence_elastic, evidence_kernel
    from .pledges import get_ledger

    evidence = await evidence_elastic.build_evidence(milestone_id, met, facts)
    if evidence is None:
        evidence = await evidence_kernel.build_evidence(milestone_id, met, facts)
    if evidence is None:
        evidence = simulation_evidence(met, facts)
    await get_ledger().append_evidence(milestone_id, evidence)
    return evidence


async def get_milestone(milestone_id: str) -> Optional[dict]:
    from .pledges import get_ledger

    return await get_ledger().get_milestone(milestone_id)


async def list_milestones() -> list[dict]:
    from .pledges import get_ledger

    return await get_ledger().list_milestones()


def latest_evidence(milestone: Optional[dict]) -> dict:
    if not milestone:
        return {}
    evidence = milestone.get("evidence") or []
    if not evidence:
        return {}
    return evidence[-1]


def latest_trusted_evidence(milestone: Optional[dict]) -> dict:
    """Newest evidence the Captain may use. Simulated KERNEL rows are skipped."""
    if not milestone:
        return {}
    for item in reversed(milestone.get("evidence") or []):
        if not isinstance(item, dict):
            continue
        if item.get("trusted") is False:
            continue
        if str(item.get("provider") or "").endswith("-simulated"):
            continue
        return item
    return {}
