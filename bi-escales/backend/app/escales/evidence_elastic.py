"""Optional Elastic evidence (feature flag off by default).

No secrets in repo: URL comes from ``ESCALES_ELASTIC_URL`` when enabled.
"""
from __future__ import annotations

import os
from typing import Any, Optional

import httpx

from .config import elastic_evidence_enabled
from .pledges import now_iso


def _local_stub(milestone_id: str, met: Optional[bool], facts: Optional[dict]) -> dict:
    return {
        "flag": "local",
        "provider": "local",
        "source": "local",
        "met": met,
        "facts": dict(facts or {}),
        "milestone_id": milestone_id,
        "recorded_at": now_iso(),
    }


async def build_evidence(
    milestone_id: str,
    met: Optional[bool],
    facts: Optional[dict],
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[dict]:
    """Return Elastic-backed evidence when enabled, else None (caller uses local)."""
    if not elastic_evidence_enabled():
        return None
    base = (os.environ.get("ESCALES_ELASTIC_URL") or "").strip().rstrip("/")
    if not base:
        return None
    url = f"{base}/escales/{milestone_id}/evidence"
    own = client is None
    http = client or httpx.AsyncClient()
    try:
        response = await http.post(
            url,
            json={"met": met, "facts": facts or {}},
            timeout=10.0,
        )
        if response.status_code >= 400:
            return _local_stub(milestone_id, met, facts)
        payload = response.json()
        if not isinstance(payload, dict):
            return _local_stub(milestone_id, met, facts)
        return {
            "flag": "elastic",
            "provider": "ELASTIC",
            "source": payload.get("source") or "elastic",
            "met": payload.get("met", met),
            "facts": dict(payload.get("facts") or facts or {}),
            "recorded_at": now_iso(),
        }
    except Exception:
        return _local_stub(milestone_id, met, facts)
    finally:
        if own:
            await http.aclose()
