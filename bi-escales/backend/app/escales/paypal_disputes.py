"""Customer Disputes v1 — list, show, accept claim, provide evidence (admin, read-only treasurer lists)."""

from __future__ import annotations

from typing import Any, Optional

from .ledger import record_finance


class DisputeNotFound(LookupError):
    pass


async def _persist_dispute_snapshot(dispute_id: str, payload: dict, *, source: str) -> None:
    await record_finance(
        "paypal_dispute_snapshot",
        dispute_id=dispute_id,
        source=source,
        status=(payload.get("status") if isinstance(payload, dict) else None),
        payload=payload,
    )


async def list_disputes(client: Any, *, start_time: Optional[str] = None) -> dict:
    payload = client.list_disputes(start_time=start_time)
    items = payload.get("items") if isinstance(payload, dict) else []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get("dispute_id"):
                await _persist_dispute_snapshot(str(item["dispute_id"]), item, source="list")
    return payload if isinstance(payload, dict) else {"items": []}


async def get_dispute(client: Any, dispute_id: str) -> dict:
    dispute_id = str(dispute_id or "").strip()
    if not dispute_id:
        raise ValueError("dispute_id is required")
    payload = client.get_dispute(dispute_id)
    if isinstance(payload, dict):
        await _persist_dispute_snapshot(dispute_id, payload, source="get")
    return payload


async def dispute_evidence_notes(*, milestone_id: str) -> str:
    """Leg facts from the Captain evidence kernel (schedule + sailed proof)."""
    from .milestones import get_milestone, latest_evidence

    milestone = await get_milestone(milestone_id)
    evidence = latest_evidence(milestone)
    if not evidence:
        return "No milestone evidence on file for this leg."
    parts: list[str] = []
    for key in ("summary", "departure_iso", "arrival_iso", "sailed_nm", "status", "source"):
        value = evidence.get(key)
        if value:
            parts.append(f"{key}: {value}")
    facts = evidence.get("facts")
    if isinstance(facts, dict):
        for key, value in facts.items():
            if value is not None and str(value).strip():
                parts.append(f"{key}: {value}")
    return "\n".join(parts) if parts else "Milestone evidence recorded (see escales audit)."


async def accept_dispute_claim(client: Any, dispute_id: str, *, note: str = "") -> dict:
    result = client.accept_dispute_claim(dispute_id, note=note)
    await record_finance("paypal_dispute_action", dispute_id=dispute_id, action="accept_claim")
    return result


async def provide_dispute_evidence(
    client: Any,
    dispute_id: str,
    *,
    milestone_id: str,
    notes: Optional[str] = None,
) -> dict:
    text = (notes or "").strip() or await dispute_evidence_notes(milestone_id=milestone_id)
    result = client.provide_dispute_evidence(
        dispute_id,
        notes=text,
        evidence_type="PROOF_OF_FULFILLMENT",
    )
    await record_finance(
        "paypal_dispute_action",
        dispute_id=dispute_id,
        action="provide_evidence",
        milestone_id=milestone_id,
    )
    return result


async def list_dispute_snapshots() -> list[dict]:
    from .ledger import list_finance_entries

    rows: list[dict] = []
    seen: set[str] = set()
    for entry in await list_finance_entries():
        if entry.get("kind") != "paypal_dispute_snapshot":
            continue
        did = str(entry.get("dispute_id") or "")
        if not did or did in seen:
            continue
        seen.add(did)
        rows.append({
            "dispute_id": did,
            "status": entry.get("status"),
            "at": entry.get("at"),
        })
    return rows
