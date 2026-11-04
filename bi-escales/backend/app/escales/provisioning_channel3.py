"""Optional Channel3 provisioning hints for capture proposals (never executes payment)."""
from __future__ import annotations

from typing import Any, Optional

from .config import channel3_enabled
from .pledges import now_iso


def attach_provisioning(proposal: dict[str, Any], milestone_id: str) -> dict[str, Any]:
    """Enrich a captain proposal with Channel3 metadata when the flag is on."""
    if not channel3_enabled():
        return proposal
    out = dict(proposal)
    out["channel3"] = {
        "status": "proposed",
        "milestone_id": milestone_id,
        "note": (
            "Provisioning Channel3 : encaissement proposé le jour du départ de l'escale ; "
            "annulé si l'escale est annulée. Aucun débit automatique."
        ),
        "at": now_iso(),
    }
    return out


def provisioning_enabled() -> bool:
    return channel3_enabled()
