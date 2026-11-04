"""Pledge state machine: created -> authorized -> captured | voided.

Nothing is captured or voided until a treasurer calls the matching route.
Forbidden transitions raise ``IllegalTransition`` (HTTP 409 at the edge).
Storage is ``escales_pledges`` when Mongo is configured, otherwise memory.
"""
from __future__ import annotations

import copy
import datetime as dt
import os
import re
import threading
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from .config import AUTH_MAX_DAYS
from .paypal_client import PayPalError, approve_link, authorization_from

PLEDGES_COLLECTION = "escales_pledges"
MILESTONES_COLLECTION = "escales_milestones"
AUDIT_COLLECTION = "escales_audit"
COLLECTIONS = (PLEDGES_COLLECTION, MILESTONES_COLLECTION, AUDIT_COLLECTION)

_AMOUNT = re.compile(r"^\d+(?:\.\d{1,2})?$")


class IllegalTransition(Exception):
    def __init__(self, current: str, target: str):
        self.current = current
        self.target = target
        super().__init__(f"forbidden transition {current} -> {target}")


class PledgeNotFound(Exception):
    def __init__(self, pledge_id: str):
        self.pledge_id = pledge_id
        super().__init__(f"pledge {pledge_id} not found")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def default_expiration() -> str:
    moment = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=AUTH_MAX_DAYS)
    return moment.replace(microsecond=0).isoformat()


def normalize_amount(raw: str) -> str:
    text = (raw or "").strip()
    if not _AMOUNT.match(text):
        raise ValueError("amount_eur must be a positive amount with at most 2 decimal places")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("amount_eur must be a positive amount with at most 2 decimal places") from exc
    if value <= 0:
        raise ValueError("amount_eur must be a positive amount with at most 2 decimal places")
    return f"{value:.2f}"


def to_public(doc: dict) -> dict:
    hidden = {"_id", "client_key"}
    out = {key: value for key, value in doc.items() if key not in hidden}
    out["id"] = doc["_id"]
    return out


def _mongo_wanted() -> bool:
    # ESCALES_STORE=memory forces the in-memory ledger (tests). Otherwise Mongo
    # is used when MONGO_URL is set, so pledges land in escales_* collections.
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

    async def insert_pledge_once(self, doc: dict) -> dict:
        with self._lock:
            key = doc.get("client_key")
            if key and key in self._by_key:
                return copy.deepcopy(self._pledges[self._by_key[key]])
            stored = copy.deepcopy(doc)
            self._pledges[stored["_id"]] = stored
            if key:
                self._by_key[key] = stored["_id"]
            return copy.deepcopy(stored)

    async def save_pledge(self, doc: dict) -> dict:
        with self._lock:
            stored = copy.deepcopy(doc)
            self._pledges[stored["_id"]] = stored
            key = stored.get("client_key")
            if key:
                self._by_key[key] = stored["_id"]
            return copy.deepcopy(stored)

    async def get_pledge(self, pledge_id: str) -> Optional[dict]:
        with self._lock:
            doc = self._pledges.get(pledge_id)
            return copy.deepcopy(doc) if doc else None

    async def find_by_client_key(self, client_key: str) -> Optional[dict]:
        with self._lock:
            pledge_id = self._by_key.get(client_key)
            if not pledge_id:
                return None
            return copy.deepcopy(self._pledges[pledge_id])

    async def list_pledges_for_milestone(self, milestone_id: str) -> list[dict]:
        with self._lock:
            return [
                copy.deepcopy(doc)
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


class MongoLedger:
    """Motor-backed escales_* collections. Not used by the default test run."""

    def __init__(self, db: Any) -> None:
        self._pledges = db[PLEDGES_COLLECTION]
        self._milestones = db[MILESTONES_COLLECTION]
        self._audit = db[AUDIT_COLLECTION]
        self._ready = False

    async def _ensure(self) -> None:
        if self._ready:
            return
        await self._pledges.create_index(
            "client_key", unique=True, sparse=True, name="escales_pledges_client_key",
        )
        await self._audit.create_index("at", name="escales_audit_at")
        self._ready = True

    async def insert_pledge_once(self, doc: dict) -> dict:
        await self._ensure()
        key = doc.get("client_key")
        if key:
            existing = await self._pledges.find_one({"client_key": key})
            if existing:
                return existing
        try:
            await self._pledges.insert_one(copy.deepcopy(doc))
        except Exception as exc:
            if key and exc.__class__.__name__ == "DuplicateKeyError":
                existing = await self._pledges.find_one({"client_key": key})
                if existing:
                    return existing
            raise
        return doc

    async def save_pledge(self, doc: dict) -> dict:
        await self._ensure()
        stored = copy.deepcopy(doc)
        await self._pledges.replace_one({"_id": stored["_id"]}, stored, upsert=True)
        return stored

    async def get_pledge(self, pledge_id: str) -> Optional[dict]:
        await self._ensure()
        return await self._pledges.find_one({"_id": pledge_id})

    async def find_by_client_key(self, client_key: str) -> Optional[dict]:
        await self._ensure()
        return await self._pledges.find_one({"client_key": client_key})

    async def list_pledges_for_milestone(self, milestone_id: str) -> list[dict]:
        await self._ensure()
        cursor = self._pledges.find({"milestone_id": milestone_id})
        return [doc async for doc in cursor]

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


def _require_text(value: str, field: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _client_key(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    key = raw.strip()
    if not key:
        return None
    if not 1 <= len(key) <= 108:
        raise ValueError("PayPal-Request-Id must be 1 to 108 characters")
    return key


async def require_pledge(pledge_id: str) -> dict:
    doc = await get_ledger().get_pledge(pledge_id)
    if doc is None:
        raise PledgeNotFound(pledge_id)
    return doc


async def create_pledge(
    *,
    amount_eur: str,
    description: str,
    milestone_id: str,
    client: Any,
    client_key: Optional[str] = None,
    contributor: Optional[str] = None,
) -> dict:
    amount = normalize_amount(amount_eur)
    description = _require_text(description, "description")
    milestone_id = _require_text(milestone_id, "milestone_id")
    key = _client_key(client_key)
    ledger = get_ledger()
    if key:
        existing = await ledger.find_by_client_key(key)
        if existing:
            return existing
    pledge_id = uuid.uuid4().hex
    idempotency_key = key or uuid.uuid4().hex
    order = client.create_authorize_order(
        amount_eur=amount,
        description=description,
        reference_id=pledge_id,
        idempotency_key=idempotency_key,
    )
    order_id = order.get("id")
    if not order_id:
        raise PayPalError(502, "order id missing")
    if key:
        existing = await ledger.find_by_client_key(key)
        if existing:
            return existing
    doc = {
        "_id": pledge_id,
        "client_key": key,
        "status": "created",
        "intent": "AUTHORIZE",
        "currency": "EUR",
        "amount_eur": amount,
        "description": description,
        "milestone_id": milestone_id,
        "contributor": (contributor or "").strip() or None,
        "order_id": order_id,
        "approve_link": approve_link(order),
        "authorization_id": None,
        "authorization_expires_at": None,
        "created_at": now_iso(),
        "history": ["created"],
    }
    return await ledger.insert_pledge_once(doc)


def _require_status(pledge: dict, expected: str, target: str) -> None:
    current = pledge.get("status")
    if current != expected:
        raise IllegalTransition(str(current), target)


async def authorize_pledge(pledge_id: str, client: Any) -> dict:
    pledge = await require_pledge(pledge_id)
    _require_status(pledge, "created", "authorized")
    order = client.authorize_order(pledge["order_id"])
    auth_id, expiration = authorization_from(order)
    pledge["status"] = "authorized"
    pledge["authorization_id"] = auth_id
    pledge["authorization_expires_at"] = expiration or default_expiration()
    pledge["history"] = list(pledge.get("history") or []) + ["authorized"]
    return await get_ledger().save_pledge(pledge)


async def capture_pledge(pledge_id: str, client: Any) -> dict:
    pledge = await require_pledge(pledge_id)
    _require_status(pledge, "authorized", "captured")
    if not pledge.get("authorization_id"):
        raise IllegalTransition("authorized", "captured")
    client.capture_authorization(pledge["authorization_id"])
    pledge["status"] = "captured"
    pledge["history"] = list(pledge.get("history") or []) + ["captured"]
    saved = await get_ledger().save_pledge(pledge)
    from .audit import record
    await record(
        "capture",
        actor="treasurer",
        pledge_id=saved["_id"],
        milestone_id=saved.get("milestone_id"),
        status="captured",
        amount_eur=saved.get("amount_eur"),
        currency="EUR",
    )
    return saved


async def void_pledge(pledge_id: str, client: Any) -> dict:
    pledge = await require_pledge(pledge_id)
    _require_status(pledge, "authorized", "voided")
    if not pledge.get("authorization_id"):
        raise IllegalTransition("authorized", "voided")
    client.void_authorization(pledge["authorization_id"])
    pledge["status"] = "voided"
    pledge["history"] = list(pledge.get("history") or []) + ["voided"]
    saved = await get_ledger().save_pledge(pledge)
    from .audit import record
    await record(
        "void",
        actor="treasurer",
        pledge_id=saved["_id"],
        milestone_id=saved.get("milestone_id"),
        status="voided",
        amount_eur=saved.get("amount_eur"),
        currency="EUR",
    )
    return saved


async def pledges_for_milestone(milestone_id: str) -> list[dict]:
    return await get_ledger().list_pledges_for_milestone(milestone_id)
