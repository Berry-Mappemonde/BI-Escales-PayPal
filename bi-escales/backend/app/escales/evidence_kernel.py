"""Optional KERNEL evidence (feature flag off by default).

A local hash is not a KERNEL attestation. It is labeled simulated and
``trusted`` is false, so the Captain does not treat it as evidence.
A real call is attempted only when ``ESCALES_KERNEL_URL`` is set; the
response is trusted only when KERNEL returns an attestation id.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Optional

import httpx

from .config import kernel_evidence_enabled
from .pledges import now_iso


def _digest(milestone_id: str, facts: Optional[dict]) -> str:
    raw = json.dumps({"milestone_id": milestone_id, "facts": facts or {}}, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _simulated(milestone_id: str, met: Optional[bool], facts: Optional[dict], endpoint: str) -> dict:
    return {
        "flag": "simulation",
        "provider": "KERNEL-simulated",
        "source": "simulated",
        "trusted": False,
        "met": met,
        "facts": {
            **(facts or {}),
            "kernel": {
                "kernel_endpoint": endpoint or "unset",
                "digest": _digest(milestone_id, facts),
                "note": "local digest only; not a KERNEL attestation",
            },
        },
        "recorded_at": now_iso(),
    }


async def build_evidence(
    milestone_id: str,
    met: Optional[bool],
    facts: Optional[dict],
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[dict]:
    """Return KERNEL evidence when enabled; otherwise None.

    Without a successful KERNEL response the record is simulated and untrusted.
    """
    if not kernel_evidence_enabled():
        return None
    endpoint = (os.environ.get("ESCALES_KERNEL_URL") or "").strip()
    if endpoint:
        own = client is None
        http = client or httpx.AsyncClient()
        try:
            response = await http.post(
                endpoint,
                json={"milestone_id": milestone_id, "met": met, "facts": facts or {}},
                timeout=10.0,
            )
            response.raise_for_status()
            body = response.json()
            attestation_id = body.get("id") if isinstance(body, dict) else None
            if attestation_id:
                return {
                    "flag": "kernel",
                    "provider": "KERNEL",
                    "source": "kernel-attestation",
                    "trusted": True,
                    "met": met,
                    "facts": {**(facts or {}), "kernel": body},
                    "recorded_at": now_iso(),
                }
        except Exception:
            pass
        finally:
            if own:
                await http.aclose()
    return _simulated(milestone_id, met, facts, endpoint)
