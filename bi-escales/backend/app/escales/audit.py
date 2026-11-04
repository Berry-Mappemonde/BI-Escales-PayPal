"""Append-only journal for Captain proposals and treasurer actions.

Stored in the ``escales_audit`` collection (in-memory when Mongo is not used).
"""
from __future__ import annotations

import uuid

from .ledger import get_ledger, now_iso

AUDIT_COLLECTION = "escales_audit"


async def record(kind: str, **fields) -> dict:
    entry = {
        "_id": uuid.uuid4().hex,
        "at": now_iso(),
        "kind": kind,
        "collection": AUDIT_COLLECTION,
    }
    entry.update(fields)
    return await get_ledger().append_audit(entry)


async def list_entries() -> list[dict]:
    return await get_ledger().list_audit()
