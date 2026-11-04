"""Optional KERNEL evidence attestation (feature flag off by default)."""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Optional

from .config import kernel_evidence_enabled
from .pledges import now_iso


def _digest(milestone_id: str, facts: Optional[dict]) -> str:
    raw = json.dumps({"milestone_id": milestone_id, "facts": facts or {}}, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


async def build_evidence(
    milestone_id: str,
    met: Optional[bool],
    facts: Optional[dict],
) -> Optional[dict]:
    """Return KERNEL attestation when enabled; otherwise None."""
    if not kernel_evidence_enabled():
        return None
    endpoint = (os.environ.get("ESCALES_KERNEL_URL") or "").strip()
    attestation = {
        "kernel_endpoint": endpoint or "local-kernel",
        "digest": _digest(milestone_id, facts),
    }
    return {
        "flag": "kernel",
        "provider": "KERNEL",
        "source": "kernel-attestation",
        "met": met,
        "facts": {**(facts or {}), "kernel": attestation},
        "recorded_at": now_iso(),
    }
