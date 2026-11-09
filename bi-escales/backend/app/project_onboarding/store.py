"""In-memory / Mongo persistence for onboard-after-payment demo projects."""

from __future__ import annotations

import copy
import os
import threading
import uuid
from typing import Any, Optional

_lock = threading.Lock()
_memory: dict[str, dict[str, Any]] = {"projects": {}, "donations": {}, "referrals": {}, "webhook_ids": {}}

COLLECTION = "escales_project_onboarding"


def referral_document_id(project_id: str) -> str:
    """Mongo _id for a referral row (distinct from the project row _id)."""
    return f"referral:{project_id}"


def _mongo_wanted() -> bool:
    mode = os.environ.get("ESCALES_STORE", "").strip().lower()
    if mode == "memory":
        return False
    if mode == "mongo":
        return True
    return bool((os.environ.get("MONGO_URL") or "").strip())


def reset_onboarding_store() -> None:
    with _lock:
        _memory["projects"].clear()
        _memory["donations"].clear()
        _memory["referrals"].clear()
        _memory["webhook_ids"].clear()


async def _collection():
    from app.db import get_db

    return get_db()[COLLECTION]


def _bucket(kind: str) -> dict[str, Any]:
    return _memory[kind]


async def save_project(doc: dict) -> dict:
    pid = str(doc.get("_id") or "").strip()
    if not pid:
        raise ValueError("project id required")
    payload = copy.deepcopy(doc)
    payload["_id"] = pid
    if _mongo_wanted():
        coll = await _collection()
        await coll.replace_one({"_id": pid, "kind": "project"}, {**payload, "kind": "project"}, upsert=True)
    with _lock:
        _bucket("projects")[pid] = payload
    return payload


async def get_project(project_id: str) -> Optional[dict]:
    pid = str(project_id or "").strip()
    if not pid:
        return None
    with _lock:
        cached = _bucket("projects").get(pid)
        if cached:
            return copy.deepcopy(cached)
    if _mongo_wanted():
        coll = await _collection()
        row = await coll.find_one({"_id": pid, "kind": "project"})
        if row:
            doc = {k: v for k, v in row.items() if k != "kind"}
            with _lock:
                _bucket("projects")[pid] = doc
            return copy.deepcopy(doc)
    return None


async def list_donations(project_id: str) -> list[dict]:
    pid = str(project_id or "").strip()
    out: list[dict] = []
    with _lock:
        for row in _bucket("donations").values():
            if str(row.get("project_id") or "") == pid:
                out.append(copy.deepcopy(row))
    if _mongo_wanted():
        coll = await _collection()
        cursor = coll.find({"kind": "donation", "project_id": pid})
        async for row in cursor:
            doc = {k: v for k, v in row.items() if k != "kind"}
            out.append(doc)
    return sorted(out, key=lambda r: str(r.get("created_at") or ""))


async def save_donation(doc: dict) -> dict:
    did = str(doc.get("_id") or "").strip() or uuid.uuid4().hex
    payload = copy.deepcopy(doc)
    payload["_id"] = did
    if _mongo_wanted():
        coll = await _collection()
        await coll.replace_one(
            {"_id": did, "kind": "donation"},
            {**payload, "kind": "donation"},
            upsert=True,
        )
    with _lock:
        _bucket("donations")[did] = payload
    return payload


async def get_donation(donation_id: str) -> Optional[dict]:
    did = str(donation_id or "").strip()
    if not did:
        return None
    with _lock:
        cached = _bucket("donations").get(did)
        if cached:
            return copy.deepcopy(cached)
    if _mongo_wanted():
        coll = await _collection()
        row = await coll.find_one({"_id": did, "kind": "donation"})
        if row:
            doc = {k: v for k, v in row.items() if k != "kind"}
            with _lock:
                _bucket("donations")[did] = doc
            return copy.deepcopy(doc)
    return None


async def save_referral(doc: dict) -> dict:
    pid = str(doc.get("project_id") or "").strip()
    if not pid:
        raise ValueError("project_id required")
    payload = copy.deepcopy(doc)
    payload["project_id"] = pid
    rid = referral_document_id(pid)
    if _mongo_wanted():
        coll = await _collection()
        await coll.replace_one(
            {"_id": rid, "kind": "referral"},
            {**payload, "kind": "referral", "_id": rid},
            upsert=True,
        )
    with _lock:
        _bucket("referrals")[pid] = payload
    return payload


async def get_referral(project_id: str) -> Optional[dict]:
    pid = str(project_id or "").strip()
    if not pid:
        return None
    with _lock:
        cached = _bucket("referrals").get(pid)
        if cached:
            return copy.deepcopy(cached)
    if _mongo_wanted():
        coll = await _collection()
        row = await coll.find_one({"kind": "referral", "project_id": pid})
        if row:
            doc = {k: v for k, v in row.items() if k != "kind"}
            with _lock:
                _bucket("referrals")[pid] = doc
            return copy.deepcopy(doc)
    return None


async def claim_webhook_event(event_id: str) -> bool:
    """Return False when this event id was already processed (idempotent)."""
    token = str(event_id or "").strip()
    if not token:
        return True
    if _mongo_wanted():
        coll = await _collection()
        existing = await coll.find_one({"_id": token, "kind": "webhook_dedup"})
        if existing:
            return False
        await coll.insert_one({"_id": token, "kind": "webhook_dedup"})
        return True
    with _lock:
        if token in _bucket("webhook_ids"):
            return False
        _bucket("webhook_ids")[token] = True
        return True
