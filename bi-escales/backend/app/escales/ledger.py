"""Append-only storage for pledges, milestones, audit, finance, and webhook dedup.

``escales_finance`` mirrors money-related lifecycle events (create, authorize,
capture, void) in parallel with the narrative ``escales_audit`` journal.
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


def _milestone_ids(milestone_id: str) -> set[str]:
    """Chat slug and the route id name the same stopover."""
    from .naviguide_bridge import resolve_milestone

    canonical = resolve_milestone(milestone_id) or milestone_id
    return {milestone_id, canonical}


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
        self._webhook_log: list[dict] = []

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

    async def find_pledge_by_capture_id(self, capture_id: str) -> Optional[dict]:
        wanted = str(capture_id or "").strip()
        if not wanted:
            return None
        with self._lock:
            for doc in self._pledges.values():
                if doc.get("capture_id") == wanted:
                    return pledge_defaults(doc)
            for entry in self._finance:
                if entry.get("kind") == "pledge_captured" and entry.get("capture_id") == wanted:
                    pledge_id = entry.get("pledge_id")
                    if pledge_id and pledge_id in self._pledges:
                        return pledge_defaults(self._pledges[pledge_id])
            return None

    async def list_pledges(self) -> list[dict]:
        with self._lock:
            return [pledge_defaults(doc) for doc in self._pledges.values()]

    async def list_pledges_for_milestone(self, milestone_id: str) -> list[dict]:
        wanted = _milestone_ids(milestone_id)
        with self._lock:
            return [
                pledge_defaults(doc)
                for doc in self._pledges.values()
                if doc.get("milestone_id") in wanted
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

    async def update_finance(self, entry_id: str, patch: dict) -> Optional[dict]:
        with self._lock:
            for row in self._finance:
                if str(row.get("_id") or "") != entry_id:
                    continue
                row.update(copy.deepcopy(patch))
                return copy.deepcopy(row)
        return None

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

    async def record_webhook_outcome(self, entry: dict) -> dict:
        stored = {
            "transmission_id": entry.get("transmission_id"),
            "event_type": entry.get("event_type"),
            "resource_id": entry.get("resource_id"),
            "pledge_id": entry.get("pledge_id"),
            "time": entry.get("time") or now_iso(),
            "outcome": entry.get("outcome"),
        }
        for key in ("verification_status", "name", "message"):
            value = entry.get(key)
            if value is not None and str(value).strip():
                stored[key] = str(value)[:200]
        with self._lock:
            self._webhook_log.append(stored)
            return copy.deepcopy(stored)

    async def list_webhook_outcomes(self) -> list[dict]:
        with self._lock:
            return [copy.deepcopy(item) for item in reversed(self._webhook_log)]


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

    async def find_pledge_by_capture_id(self, capture_id: str) -> Optional[dict]:
        wanted = str(capture_id or "").strip()
        if not wanted:
            return None
        await self._ensure()
        doc = await self._pledges.find_one({"capture_id": wanted})
        if doc:
            return pledge_defaults(doc)
        fin = await self._finance.find_one({"kind": "pledge_captured", "capture_id": wanted})
        if fin and fin.get("pledge_id"):
            return await self.get_pledge(str(fin["pledge_id"]))
        return None

    async def list_pledges(self) -> list[dict]:
        await self._ensure()
        cursor = self._pledges.find({})
        return [pledge_defaults(doc) async for doc in cursor]

    async def list_pledges_for_milestone(self, milestone_id: str) -> list[dict]:
        await self._ensure()
        cursor = self._pledges.find({"milestone_id": {"$in": list(_milestone_ids(milestone_id))}})
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

    async def update_finance(self, entry_id: str, patch: dict) -> Optional[dict]:
        await self._ensure()
        result = await self._finance.update_one(
            {"_id": entry_id},
            {"$set": copy.deepcopy(patch)},
        )
        if not result.matched_count:
            return None
        doc = await self._finance.find_one({"_id": entry_id})
        return doc

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

    async def record_webhook_outcome(self, entry: dict) -> dict:
        await self._ensure()
        stored = {
            "_id": uuid.uuid4().hex,
            "log": True,
            "transmission_id": entry.get("transmission_id"),
            "event_type": entry.get("event_type"),
            "resource_id": entry.get("resource_id"),
            "pledge_id": entry.get("pledge_id"),
            "time": entry.get("time") or now_iso(),
            "outcome": entry.get("outcome"),
        }
        for key in ("verification_status", "name", "message"):
            value = entry.get(key)
            if value is not None and str(value).strip():
                stored[key] = str(value)[:200]
        await self._webhooks.insert_one(copy.deepcopy(stored))
        public = dict(stored)
        public.pop("_id", None)
        public.pop("log", None)
        return public

    async def list_webhook_outcomes(self) -> list[dict]:
        await self._ensure()
        cursor = self._webhooks.find({"log": True}).sort("time", -1)
        rows = []
        async for doc in cursor:
            public = dict(doc)
            public.pop("_id", None)
            public.pop("log", None)
            rows.append(public)
        return rows


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


async def update_finance_entry(entry_id: str, patch: dict) -> Optional[dict]:
    return await get_ledger().update_finance(entry_id, patch)


async def record_webhook_outcome(entry: dict) -> dict:
    return await get_ledger().record_webhook_outcome(entry)


async def list_webhook_outcomes() -> list[dict]:
    return await get_ledger().list_webhook_outcomes()


_SPENDING_CAP = Decimal("10000.00")


def _euros(value: Any) -> Decimal:
    """Stored journal amount. NaN and Infinity count as zero, never 500."""
    try:
        amount = Decimal(str(value if value is not None else "0"))
        if not amount.is_finite():
            return Decimal("0.00")
        return amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def _stopover_slug(value: str) -> str:
    """Canonical bare slug. ``mayotte`` and ``dep-dzaoudzi-mayotte`` are one stop."""
    from .naviguide_bridge import resolve_milestone
    from ..escales_names import _slug

    resolved = resolve_milestone(str(value or ""))
    if resolved and str(resolved).startswith("dep-"):
        return str(resolved)[4:]
    if resolved:
        return str(resolved)
    return _slug(str(value or ""))


def _leg_id(milestone_id: str) -> Optional[str]:
    """Canonical cabin-leg id, or None when this is a stopover."""
    from .naviguide_bridge import leg_by_id, resolve_milestone

    token = str(milestone_id or "").strip()
    if not token:
        return None
    leg = leg_by_id(token)
    if leg:
        return str(leg["id"])
    resolved = resolve_milestone(token)
    if resolved and str(resolved).startswith("leg-"):
        return str(resolved)
    return None


async def _require_stopover(milestone_id: str) -> str:
    from .pledges import _known_stopover

    slug = _stopover_slug(milestone_id)
    if not slug or str(slug).startswith("leg-") or not await _known_stopover(slug):
        raise LookupError("milestone not found")
    return slug


def _euros_text(amount: Decimal) -> str:
    return f"{amount.quantize(Decimal('0.01')):.2f}"


def to_public_fund(fund: dict) -> dict:
    """Aggregated totals. No journal lines and no pledge ids."""
    captured = str(fund.get("income_eur") or "0.00")
    return {
        "milestone_id": fund.get("milestone_id"),
        "currency": fund.get("currency") or "EUR",
        "income_eur": captured,
        "captured_eur": str(fund.get("captured_eur") or captured),
        "authorized_eur": str(fund.get("authorized_eur") or "0.00"),
        "spending_eur": str(fund.get("spending_eur") or "0.00"),
        "refunded_eur": str(fund.get("refunded_eur") or "0.00"),
        "balance_eur": str(fund.get("balance_eur") or "0.00"),
        "overdrawn": bool(fund.get("overdrawn")),
    }


def to_public_project_donation_total(fund: dict) -> dict:
    """Public BI project crowdfunding totals only (pattern: ``to_public_fund`` stopover aggregates).

    Donor-facing read: captured amount, donation count, refunds. No journal lines or ids.
    """
    income = fund.get("income")
    donation_count = len(income) if isinstance(income, list) else 0
    captured = str(fund.get("captured_eur") or fund.get("income_eur") or "0.00")
    return {
        "project_id": fund.get("milestone_id"),
        "currency": fund.get("currency") or "EUR",
        "amount_eur": captured,
        "donation_count": donation_count,
        "refunded_eur": str(fund.get("refunded_eur") or "0.00"),
    }


def _public_finance(entry: dict) -> dict:
    return {
        "id": entry.get("_id"),
        "at": entry.get("at"),
        "kind": entry.get("kind"),
        "amount_eur": _euros_text(_euros(entry.get("amount_eur"))),
        "currency": entry.get("currency") or "EUR",
        "description": entry.get("description"),
        "pledge_id": entry.get("pledge_id"),
        "pledge_kind": entry.get("pledge_kind"),
        "target_id": entry.get("target_id"),
    }


async def _income_line(entry: dict) -> dict:
    """Captured line, with the pledge wording and the kind that was promised."""
    public = _public_finance(entry)
    pledge_id = entry.get("pledge_id")
    pledge = await get_ledger().get_pledge(pledge_id) if pledge_id else None
    if not pledge:
        return public
    row = pledge_defaults(pledge) or pledge
    public["description"] = row.get("description") or public.get("description")
    public["pledge_kind"] = row.get("kind")
    public["target_id"] = row.get("target_id")
    return public


# Pledges with an empty milestone. ``project`` and ``fund`` are not stopovers.
_PROJECT_BUCKET = "projet"
_FUND_BUCKET = "fonds-commun"
_PROJECT_ALIASES = {"project", "projet", "project_pledge", "project-pledge"}
_FUND_ALIASES = {"fund", "fonds-commun", "common-fund", "common_fund", "caisse"}


def _unplaced_bucket(milestone_id: str) -> Optional[str]:
    """``project`` and ``fund`` name the two totals that have no stopover."""
    token = (milestone_id or "").strip().casefold()
    if token in _PROJECT_ALIASES:
        return _PROJECT_BUCKET
    if token in _FUND_ALIASES:
        return _FUND_BUCKET
    return None


def _entry_in_unplaced(entry: dict, bucket: str) -> bool:
    """Captured project or common-fund lines whose milestone was left empty.

    A common-fund pledge filed on a stopover stays on that stopover.
    """
    milestone = str(entry.get("milestone_id") or "").strip().casefold()
    kind = str(entry.get("pledge_kind") or "").strip().casefold()
    target = str(entry.get("target_id") or "").strip().casefold()
    if bucket == _PROJECT_BUCKET:
        aliases = _PROJECT_ALIASES
        pledge_kind = "project_pledge"
        target_id = _PROJECT_BUCKET
    else:
        aliases = _FUND_ALIASES
        pledge_kind = "common_fund"
        target_id = _FUND_BUCKET
    if milestone and milestone not in aliases:
        return False
    if kind == pledge_kind or target == target_id:
        return True
    return entry.get("kind") == "spending" and milestone in aliases


def _entry_for_project_target(entry: dict, target: str) -> bool:
    """Finance lines for one BI project ``target_id`` (captured minus refunds)."""
    wanted = str(target or "").strip().casefold()
    if not wanted:
        return False
    entry_target = str(entry.get("target_id") or "").strip().casefold()
    if entry_target != wanted:
        return False
    milestone = str(entry.get("milestone_id") or "").strip().casefold()
    if milestone and milestone not in _PROJECT_ALIASES:
        return False
    kind = str(entry.get("kind") or "")
    pledge_kind = str(entry.get("pledge_kind") or "").casefold()
    if kind in {"pledge_captured", "pledge_refunded"}:
        return pledge_kind == "project_pledge"
    if kind == "spending":
        return str(entry.get("milestone_id") or "").strip().casefold() == wanted
    return False


_PROJECT_TARGET_SLUG = re.compile(r"^[a-z0-9-]+$")


async def _project_fund_target(milestone_id: str) -> Optional[str]:
    """Per-project fund id when the URL names a ``target_id``, not the aggregate ``projet``."""
    token = str(milestone_id or "").strip()
    if not token or _unplaced_bucket(token) or _leg_id(token):
        return None
    slug = token.casefold()
    if slug in _FUND_ALIASES or not _PROJECT_TARGET_SLUG.fullmatch(slug):
        return None
    try:
        await _require_stopover(token)
        return None
    except LookupError:
        pass
    for entry in await list_finance_entries():
        if _entry_for_project_target(entry, slug):
            return slug
    for row in await get_ledger().list_pledges():
        if str(row.get("kind") or "") != "project_pledge":
            continue
        if str(row.get("target_id") or "").strip().casefold() != slug:
            continue
        if str(row.get("milestone_id") or "").strip() and str(row.get("milestone_id") or "").strip().casefold() not in _PROJECT_ALIASES:
            continue
        return slug
    return None


def fund_milestone_for_pledge(pledge: dict) -> str:
    """Route id for ``fund_for_milestone`` from a pledge row."""
    row = pledge_defaults(pledge) if pledge else {}
    kind = str(row.get("kind") or "")
    milestone = str(row.get("milestone_id") or "").strip()
    target = str(row.get("target_id") or "").strip()
    if kind == "project_pledge":
        if target and target.casefold() not in _PROJECT_ALIASES:
            return target
        return _PROJECT_BUCKET
    if kind == "common_fund" and not milestone:
        return _FUND_BUCKET
    if milestone:
        return milestone
    return target


async def _assemble_fund(milestone_id: str, entries: list[dict]) -> dict:
    """Same totals the stopover fund route already returns."""
    income = [entry for entry in entries if entry.get("kind") == "pledge_captured"]
    spending = [entry for entry in entries if entry.get("kind") == "spending"]
    refunds = [entry for entry in entries if entry.get("kind") == "pledge_refunded"]
    income_total = sum((_euros(entry.get("amount_eur")) for entry in income), Decimal("0.00"))
    spending_total = sum((_euros(entry.get("amount_eur")) for entry in spending), Decimal("0.00"))
    refund_total = sum((_euros(entry.get("amount_eur")) for entry in refunds), Decimal("0.00"))
    balance = income_total - spending_total - refund_total
    return {
        "milestone_id": milestone_id,
        "currency": "EUR",
        "income_eur": _euros_text(income_total),
        "spending_eur": _euros_text(spending_total),
        "refunded_eur": _euros_text(refund_total),
        "balance_eur": _euros_text(balance),
        "overdrawn": spending_total + refund_total > income_total,
        "income": [await _income_line(entry) for entry in income],
        "spending": [_public_finance(entry) for entry in spending],
        "captured_eur": _euros_text(income_total),
        "authorized_eur": "0.00",
    }


def _pledge_on_stop(row: dict, slug: str) -> bool:
    return _stopover_slug(str(row.get("milestone_id") or "")) == slug


def _pledge_on_leg(row: dict, leg_id: str) -> bool:
    return str(row.get("milestone_id") or "") == leg_id or str(row.get("target_id") or "") == leg_id


def _pledge_in_bucket(row: dict, bucket: str) -> bool:
    return _entry_in_unplaced(
        {
            "milestone_id": row.get("milestone_id"),
            "pledge_kind": row.get("kind"),
            "target_id": row.get("target_id"),
            "kind": "pledge_captured",
        },
        bucket,
    )


async def _authorized_eur(match) -> str:
    """Sum of pledges still authorized. Captured money stays in the journal."""
    total = Decimal("0.00")
    for row in await get_ledger().list_pledges():
        if not row or row.get("status") != "authorized":
            continue
        if match(row):
            total += _euros(row.get("amount_eur"))
    return _euros_text(total)


async def fund_for_milestone(milestone_id: str) -> dict:
    """Income is captured pledges. Spending is what the treasurer entered.

    ``dep-lorient`` and ``lorient`` are the same stopover. A cabin leg is its
    own fund (``leg-…``), not the ports at either end. Unknown slugs raise
    ``LookupError``. ``overdrawn`` is true when spending is above income.

    ``project`` and ``fund`` are the treasurer totals for pledges that left
    ``milestone_id`` empty (a project pledge, or the boat's common fund).
    """
    bucket = _unplaced_bucket(milestone_id)
    if bucket:
        rows = [
            entry for entry in await list_finance_entries() if _entry_in_unplaced(entry, bucket)
        ]
        fund = await _assemble_fund(bucket, rows)
        fund["authorized_eur"] = await _authorized_eur(lambda row: _pledge_in_bucket(row, bucket))
        return fund
    project_target = await _project_fund_target(milestone_id)
    if project_target:
        rows = [
            entry
            for entry in await list_finance_entries()
            if _entry_for_project_target(entry, project_target)
        ]
        fund = await _assemble_fund(project_target, rows)
        fund["authorized_eur"] = await _authorized_eur(
            lambda row: str(row.get("kind") or "") == "project_pledge"
            and str(row.get("target_id") or "").strip().casefold() == project_target
            and (
                not str(row.get("milestone_id") or "").strip()
                or str(row.get("milestone_id") or "").strip().casefold() in _PROJECT_ALIASES
            )
        )
        return fund
    leg_id = _leg_id(milestone_id)
    if leg_id:
        rows = [
            entry
            for entry in await list_finance_entries()
            if str(entry.get("milestone_id") or "") == leg_id
        ]
        fund = await _assemble_fund(leg_id, rows)
        fund["authorized_eur"] = await _authorized_eur(lambda row: _pledge_on_leg(row, leg_id))
        return fund
    slug = await _require_stopover(milestone_id)
    rows = [
        entry
        for entry in await list_finance_entries()
        if _stopover_slug(str(entry.get("milestone_id") or "")) == slug
    ]
    fund = await _assemble_fund(slug, rows)
    fund["authorized_eur"] = await _authorized_eur(lambda row: _pledge_on_stop(row, slug))
    return fund


async def record_spending(milestone_id: str, amount_eur: str, description: str) -> dict:
    """Treasurer spending for one stopover or one cabin leg. It does not call PayPal.

    The amount uses the same two-decimal check as a pledge, and stays at or
    under 10 000.00 EUR. It cannot push that fund's balance below zero.
    A cabin leg is its own fund, not the ports at either end.
    """
    from .pledges import normalize_amount

    amount_text = normalize_amount(amount_eur)
    amount = Decimal(amount_text)
    if amount > _SPENDING_CAP:
        raise ValueError("amount_eur must be at most 10000.00 EUR")
    text = (description or "").strip()
    if not text:
        raise ValueError("description is required")
    leg_id = _leg_id(milestone_id)
    if leg_id:
        bucket = leg_id

        def on_bucket(entry: dict) -> bool:
            return str(entry.get("milestone_id") or "") == leg_id
    else:
        bucket = await _require_stopover(milestone_id)

        def on_bucket(entry: dict) -> bool:
            return _stopover_slug(str(entry.get("milestone_id") or "")) == bucket

    income_total = Decimal("0.00")
    spending_total = Decimal("0.00")
    refund_total = Decimal("0.00")
    for entry in await list_finance_entries():
        if not on_bucket(entry):
            continue
        if entry.get("kind") == "pledge_captured":
            income_total += _euros(entry.get("amount_eur"))
        elif entry.get("kind") == "spending":
            spending_total += _euros(entry.get("amount_eur"))
        elif entry.get("kind") == "pledge_refunded":
            refund_total += _euros(entry.get("amount_eur"))
    if spending_total + refund_total + amount > income_total:
        raise ValueError("spending must not make the balance negative")
    return await record_finance(
        "spending",
        milestone_id=bucket,
        amount_eur=amount_text,
        currency="EUR",
        description=text,
        actor="treasurer",
    )
