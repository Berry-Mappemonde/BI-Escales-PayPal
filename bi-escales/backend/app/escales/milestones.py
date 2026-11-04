"""Milestone evidence and the number filter.

NAVIGUIDE evidence posted through the API is flagged ``simulation``.
The decision (capture, void, or wait) comes from that evidence. The model
only writes the sentence; ``filter_numbers`` drops any figure it was not given.
"""
from __future__ import annotations

import re
from typing import Any, Optional

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


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


def filter_numbers(text: str, facts: Any) -> str:
    """Replace any figure that is not already present in ``facts``."""
    allowed = allowed_numbers(facts)
    return _NUMBER.sub(lambda match: match.group(0) if match.group(0) in allowed else "[?]", text or "")


def decision_for(met: Optional[bool]) -> str:
    """Rules on facts. The model does not choose."""
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
