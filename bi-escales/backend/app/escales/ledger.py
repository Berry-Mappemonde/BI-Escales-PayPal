"""Append-only storage for pledges, milestones, audit, finance, and webhook dedup.

``escales_finance`` mirrors money-related lifecycle events (create, authorize,
capture, void) in parallel with the narrative ``escales_audit`` journal.
"""
from __future__ import annotations

import copy
import datetime as dt
import os
import threading
import uuid
from typing import Any, Optional

PLEDGES_COLLECTION = "escales_pledges"
MILESTONES_COLLECTION = "escales_milestones"
AUDIT_COLLECTION = "escales_audit"
FINANCE_COLLECTION = "escales_finance"
WEBHOOKS_COLLECTION = "escales_webhooks"

COLLECTIONS = (
    PLEDGES_COLLECTION,
    MILESTONES_COLLECTION,
    AUDIT_COLLECTION,
    FINANCE_COLLECTION,
    WEBHOOKS_COLLECTION,
)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def pledge_defaults(doc: Optional[dict]) -> Optional[dict]:
    """Promesse mille déjà stockée : ``kind`` manque, la cible est le jalon.

    Copie le document. Ne réécrit pas la ligne d'origine, pour qu'une lecture
    d'un vieux document mémoire ou Mongo reste compatible.
    """
    if not doc:
        return None
    out = copy.deepcopy(doc)
    kind = str(out.get("kind") or "").strip().lower()
    out["kind"] = kind or "mile"
    target = str(out.get("target_id") or "").strip()
    if target:
        out["target_id"] = target
    else:
        milestone = str(out.get("milestone_id") or "").strip()
        out["target_id"] = milestone or None
    return out


def _mongo_wanted() -> bool:
    mode = os.environ.get("ESCALES_STORE", "").strip().lower()
    if mode == "memory":
        return False
    if mode == "mongo":
        return True
    return bool((os.environ.get("MONGO_URL") or "").strip())


class MemoryLedger:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pledges: dict[str, dict] = {}
        self._by_key: dict[str, str] = {}
        self._milestones: dict[str, dict] = {}
        self._audit: list[dict] = []
        self._finance: list[dict] = []
        self._webhooks: set[str] = set()

    async def insert_pledge_once(self, doc: dict) -> dict:
        with self._lock:
            key = doc.get("client_key")
            if key and key in self._by_key:
                return pledge_defaults(self._pledges[self._by_key[key]])
            stored = pledge_defaults(doc)
            self._pledges[stored["_id"]] = stored
            if key:
                self._by_key[key] = stored["_id"]
            return copy.deepcopy(stored)

    async def save_pledge(self, doc: dict) -> dict:
        with self._lock:
            stored = pledge_defaults(doc)
            self._pledges[stored["_id"]] = stored
            key = stored.get("client_key")
            if key:
                self._by_key[key] = stored["_id"]
            return copy.deepcopy(stored)

    async def get_pledge(self, pledge_id: str) -> Optional[dict]:
        with self._lock:
            return pledge_defaults(self._pledges.get(pledge_id))

    async def find_by_client_key(self, client_key: str) -> Optional[dict]:
        with self._lock:
            pledge_id = self._by_key.get(client_key)
            if not pledge_id:
                return None
            return pledge_defaults(self._pledges[pledge_id])

    async def find_pledge_by_order_id(self, order_id: str) -> Optional[dict]:
        with self._lock:
            for doc in self._pledges.values():
                if doc.get("order_id") == order_id:
                    return pledge_defaults(doc)
            return None

    async def list_pledges_for_milestone(self, milestone_id: str) -> list[dict]:
        with self._lock:
            return [
                pledge_defaults(doc)
                for doc in self._pledges.values()
                if doc.get("milestone_id") == milestone_id
            ]

    async def append_evidence(self, milestone_id: str, evidence: dict) -> dict:
        with self._lock:
            doc = self._milestones.get(milestone_id)
            if doc is None:
                doc = {
                    "_id": milestone_id,
                    "evidence": [],
                    "proposal": None,
                    "updated_at": evidence.get("recorded_at"),
                }
                self._milestones[milestone_id] = doc
            doc["evidence"].append(copy.deepcopy(evidence))
            doc["updated_at"] = evidence.get("recorded_at")
            return copy.deepcopy(evidence)

    async def get_milestone(self, milestone_id: str) -> Optional[dict]:
        with self._lock:
            doc = self._milestones.get(milestone_id)
            return copy.deepcopy(doc) if doc else None

    async def ensure_milestone(self, milestone_id: str, meta: Optional[dict] = None) -> dict:
        with self._lock:
            doc = self._milestones.get(milestone_id)
            if doc is None:
                doc = {
                    "_id": milestone_id,
                    "evidence": [],
                    "proposal": None,
                    "meta": copy.deepcopy(meta or {}),
                    "updated_at": now_iso(),
                }
                self._milestones[milestone_id] = doc
            elif meta:
                doc["meta"] = {**(doc.get("meta") or {}), **copy.deepcopy(meta)}
                doc["updated_at"] = now_iso()
            return copy.deepcopy(doc)

    async def list_milestones(self) -> list[dict]:
        with self._lock:
            return [copy.deepcopy(doc) for doc in self._milestones.values()]

    async def set_proposal(self, milestone_id: str, proposal: dict) -> dict:
        with self._lock:
            doc = self._milestones.get(milestone_id)
            if doc is None:
                doc = {"_id": milestone_id, "evidence": [], "proposal": None, "updated_at": now_iso()}
                self._milestones[milestone_id] = doc
            doc["proposal"] = copy.deepcopy(proposal)
            doc["updated_at"] = proposal.get("at") or now_iso()
            return copy.deepcopy(doc)

    async def append_audit(self, entry: dict) -> dict:
        with self._lock:
            stored = copy.deepcopy(entry)
            self._audit.append(stored)
            return copy.deepcopy(stored)

    async def list_audit(self) -> list[dict]:
        with self._lock:
            return [copy.deepcopy(entry) for entry in self._audit]

    async def append_finance(self, entry: dict) -> dict:
        with self._lock:
            stored = copy.deepcopy(entry)
            self._finance.append(stored)
            return copy.deepcopy(stored)

    async def list_finance(self) -> list[dict]:
        with self._lock:
            return [copy.deepcopy(entry) for entry in self._finance]

    async def has_webhook(self, transmission_id: str) -> bool:
        with self._lock:
            return transmission_id in self._webhooks

    async def claim_webhook(self, transmission_id: str, meta: dict) -> bool:
        """Return True when this transmission_id is new (caller should process)."""
        with self._lock:
            if transmission_id in self._webhooks:
                return False
            self._webhooks.add(transmission_id)
            return True


class MongoLedger:
    """Motor-backed escales_* collections. Not used by the default test run."""

    def __init__(self, db: Any) -> None:
        self._pledges = db[PLEDGES_COLLECTION]
        self._milestones = db[MILESTONES_COLLECTION]
        self._audit = db[AUDIT_COLLECTION]
        self._finance = db[FINANCE_COLLECTION]
        self._webhooks = db[WEBHOOKS_COLLECTION]
        self._ready = False

    async def _ensure(self) -> None:
        if self._ready:
            return
        await self._pledges.create_index(
            "client_key", unique=True, sparse=True, name="escales_pledges_client_key",
        )
        await self._pledges.create_index("order_id", name="escales_pledges_order_id")
        await self._audit.create_index("at", name="escales_audit_at")
        await self._finance.create_index("at", name="escales_finance_at")
        await self._webhooks.create_index(
            "_id", unique=True, name="escales_webhooks_id",
        )
        self._ready = True

    async def insert_pledge_once(self, doc: dict) -> dict:
        await self._ensure()
        key = doc.get("client_key")
        if key:
            existing = await self._pledges.find_one({"client_key": key})
            if existing:
                return pledge_defaults(existing)
        stored = pledge_defaults(doc)
        try:
            await self._pledges.insert_one(copy.deepcopy(stored))
        except Exception as exc:
            if key and exc.__class__.__name__ == "DuplicateKeyError":
                existing = await self._pledges.find_one({"client_key": key})
                if existing:
                    return pledge_defaults(existing)
            raise
        return stored

    async def save_pledge(self, doc: dict) -> dict:
        await self._ensure()
        stored = pledge_defaults(doc)
        await self._pledges.replace_one({"_id": stored["_id"]}, copy.deepcopy(stored), upsert=True)
        return stored

    async def get_pledge(self, pledge_id: str) -> Optional[dict]:
        await self._ensure()
        return pledge_defaults(await self._pledges.find_one({"_id": pledge_id}))

    async def find_by_client_key(self, client_key: str) -> Optional[dict]:
        await self._ensure()
        return pledge_defaults(await self._pledges.find_one({"client_key": client_key}))

    async def find_pledge_by_order_id(self, order_id: str) -> Optional[dict]:
        await self._ensure()
        return pledge_defaults(await self._pledges.find_one({"order_id": order_id}))

    async def list_pledges_for_milestone(self, milestone_id: str) -> list[dict]:
        await self._ensure()
        cursor = self._pledges.find({"milestone_id": milestone_id})
        return [pledge_defaults(doc) async for doc in cursor]

    async def append_evidence(self, milestone_id: str, evidence: dict) -> dict:
        await self._ensure()
        await self._milestones.update_one(
            {"_id": milestone_id},
            {
                "$push": {"evidence": evidence},
                "$set": {"updated_at": evidence.get("recorded_at")},
                "$setOnInsert": {"proposal": None},
            },
            upsert=True,
        )
        return evidence

    async def get_milestone(self, milestone_id: str) -> Optional[dict]:
        await self._ensure()
        return await self._milestones.find_one({"_id": milestone_id})

    async def ensure_milestone(self, milestone_id: str, meta: Optional[dict] = None) -> dict:
        await self._ensure()
        existing = await self._milestones.find_one({"_id": milestone_id})
        if existing is None:
            doc = {
                "_id": milestone_id,
                "evidence": [],
                "proposal": None,
                "meta": copy.deepcopy(meta or {}),
                "updated_at": now_iso(),
            }
            await self._milestones.insert_one(doc)
            return doc
        if meta:
            merged = {**(existing.get("meta") or {}), **copy.deepcopy(meta)}
            await self._milestones.update_one(
                {"_id": milestone_id},
                {"$set": {"meta": merged, "updated_at": now_iso()}},
            )
            existing = await self._milestones.find_one({"_id": milestone_id})
        return existing or {"_id": milestone_id, "evidence": [], "proposal": None, "meta": meta or {}}

    async def list_milestones(self) -> list[dict]:
        await self._ensure()
        cursor = self._milestones.find({})
        return [doc async for doc in cursor]

    async def set_proposal(self, milestone_id: str, proposal: dict) -> dict:
        await self._ensure()
        await self._milestones.update_one(
            {"_id": milestone_id},
            {
                "$set": {"proposal": proposal, "updated_at": proposal.get("at") or now_iso()},
                "$setOnInsert": {"evidence": []},
            },
            upsert=True,
        )
        doc = await self._milestones.find_one({"_id": milestone_id})
        return doc or {"_id": milestone_id, "proposal": proposal, "evidence": []}

    async def append_audit(self, entry: dict) -> dict:
        await self._ensure()
        stored = copy.deepcopy(entry)
        await self._audit.insert_one(stored)
        return stored

    async def list_audit(self) -> list[dict]:
        await self._ensure()
        cursor = self._audit.find({}).sort("at", 1)
        return [doc async for doc in cursor]

    async def append_finance(self, entry: dict) -> dict:
        await self._ensure()
        stored = copy.deepcopy(entry)
        await self._finance.insert_one(stored)
        return stored

    async def list_finance(self) -> list[dict]:
        await self._ensure()
        cursor = self._finance.find({}).sort("at", 1)
        return [doc async for doc in cursor]

    async def has_webhook(self, transmission_id: str) -> bool:
        await self._ensure()
        doc = await self._webhooks.find_one({"_id": transmission_id})
        return doc is not None

    async def claim_webhook(self, transmission_id: str, meta: dict) -> bool:
        await self._ensure()
        doc = {"_id": transmission_id, "at": now_iso(), **meta}
        try:
            await self._webhooks.insert_one(doc)
            return True
        except Exception as exc:
            if exc.__class__.__name__ == "DuplicateKeyError":
                return False
            raise


_ledger: Any = None


def reset_ledger() -> None:
    global _ledger
    _ledger = None


def get_ledger() -> Any:
    global _ledger
    if _ledger is None:
        if _mongo_wanted():
            from app.db import db
            _ledger = MongoLedger(db)
        else:
            _ledger = MemoryLedger()
    return _ledger


async def record_finance(kind: str, **fields) -> dict:
    entry = {
        "_id": uuid.uuid4().hex,
        "at": now_iso(),
        "kind": kind,
        "collection": FINANCE_COLLECTION,
    }
    entry.update(fields)
    return await get_ledger().append_finance(entry)


async def list_finance_entries() -> list[dict]:
    return await get_ledger().list_finance()
