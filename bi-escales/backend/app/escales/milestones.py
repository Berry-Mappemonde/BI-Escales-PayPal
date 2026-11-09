"""Milestone evidence and the number filter.

NAVIGUIDE evidence posted through the API is flagged ``simulation``.
The decision (capture, void, or wait) comes from that evidence. A model
proposal is advisory. ``filter_numbers`` drops a figure that is neither in
the evidence nor the sum or difference of two figures that are.
"""
from __future__ import annotations

import contextlib
import contextvars
import datetime as dt
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


def decision_for(met: Optional[bool]) -> str:
    """Rules on facts. A model proposal does not change this."""
    if met is True:
        return "capture"
    if met is False:
        return "void"
    return "wait"


def decision_for_evidence(evidence: Optional[dict], milestone: Optional[dict] = None) -> str:
    """Same capture rules as ``departure_clock.CAPTURE_RULES_EN`` (stop arrival, leg departure)."""
    row = evidence or {}
    facts = row.get("facts") if isinstance(row.get("facts"), dict) else {}
    met = row.get("met")
    meta = milestone.get("meta") if isinstance(milestone, dict) else None
    if isinstance(meta, dict) and meta.get("capture_on") == "departure":
        if facts.get("cancelled") is True or facts.get("departed") is False:
            return "void"
        if facts.get("departed") is True or met is True:
            return "capture"
        if met is False:
            return "void"
        return "wait"
    return decision_for(met if isinstance(met, bool) else None)


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


async def record_captain_review_approval(
    milestone_id: str,
    *,
    at: Optional[str] = None,
) -> dict[str, Any]:
    """Append the approved verdict and voyage-clock time; never infer it later."""
    from .config import simulated_now
    from .ledger import record_finance
    from .naviguide_bridge import resolve_milestone

    mid = (milestone_id or "").strip()
    if not mid:
        raise ValueError("milestone_id is required")
    milestone = await get_milestone(mid)
    mid = resolve_milestone(mid) or mid
    if not (milestone or {}).get("proposal"):
        milestone = await get_milestone(mid)
    review = (milestone or {}).get("proposal") or {}
    proposal = review.get("proposal") if isinstance(review, dict) else None
    if not isinstance(proposal, str) or proposal not in {"capture", "void", "wait", "reauthorize"}:
        raise ValueError("a Captain review is required before approval")
    approved_at = (at or "").strip() or simulated_now().isoformat()
    await record_finance(
        "captain_review_approved", milestone_id=mid, proposal=proposal,
        proposal_at=review.get("at"), at=approved_at,
        recorded_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    )
    return {"milestone_id": mid, "approved": True, "proposal": proposal, "at": approved_at}


_DEMO_ARRIVAL_APPROVAL: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "escales_demo_arrival_approval", default=None,
)


@contextlib.contextmanager
def demo_arrival_approval(milestone_id: str):
    """Treat ``milestone_id`` as approved for capture inside this block only.

    Used by the keyed judge-moment route. Nothing is persisted: once the block
    exits, ``captain_review_approved`` reads only the real finance journal again.
    """
    from .naviguide_bridge import resolve_milestone

    mid = (milestone_id or "").strip()
    token = _DEMO_ARRIVAL_APPROVAL.set(resolve_milestone(mid) or mid)
    try:
        yield
    finally:
        _DEMO_ARRIVAL_APPROVAL.reset(token)


async def captain_review_approved(
    milestone_id: str, *, now: Optional[dt.datetime] = None,
) -> bool:
    """Only a capture review and approval at/after arrival (or departure) qualify.

    Legacy approvals without a verdict or a valid clock time remain in the
    journal, but cannot authorize capture. A clock rewind cannot use a future approval.
    """
    from .config import simulated_now
    from .departure_clock import _parse_moment
    from .ledger import list_finance_entries
    from .naviguide_bridge import resolve_milestone, resolve_schedule_milestone

    mid = (milestone_id or "").strip()
    if not mid:
        return False
    mid = resolve_milestone(mid) or mid
    demo_mid = _DEMO_ARRIVAL_APPROVAL.get()
    if demo_mid and demo_mid == mid:
        return True
    milestone = await resolve_schedule_milestone(mid)
    meta = (milestone or {}).get("meta") or {}
    anchor_key = "departure_iso" if meta.get("capture_on") == "departure" else "arrival_iso"
    anchor = _parse_moment(str(meta.get(anchor_key) or ""))
    if anchor is None:
        return False
    approvals = []
    for entry in await list_finance_entries():
        if entry.get("kind") != "captain_review_approved":
            continue
        entry_mid = str(entry.get("milestone_id") or "")
        if (resolve_milestone(entry_mid) or entry_mid) != mid:
            continue
        approvals.append(entry)
    if not approvals:
        return False
    # Mongo lists finance by `at`, whereas memory uses insertion order. The
    # voyage clock can be pinned or rewound; use recording time only for order.
    entry = max(approvals, key=lambda row: str(row.get("recorded_at") or ""))
    approved_at = _parse_moment(str(entry.get("at") or ""))
    proposal_at = _parse_moment(str(entry.get("proposal_at") or ""))
    return (
        entry.get("proposal") == "capture"
        and approved_at is not None
        and proposal_at is not None
        and anchor <= proposal_at <= approved_at <= (now or simulated_now())
    )
