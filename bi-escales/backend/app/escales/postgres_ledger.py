"""Render Postgres ledger. Survives a free web service spin-down.

The free web service disk does not. This store is used only when
``ESCALES_POSTGRES_ENABLED`` is on and ``DATABASE_URL`` is set. Tests and the
local demo stay on the in-memory ledger.
"""
from __future__ import annotations

import copy
import json
import threading
from typing import Any, Optional

from .ledger import now_iso


class PostgresLedger:
    def __init__(self, dsn: str) -> None:
        import psycopg

        self._lock = threading.Lock()
        self._conn = psycopg.connect(dsn, autocommit=True)
        self._init()

    def close(self) -> None:
        self._conn.close()

    def _init(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS escales_pledges (
                id TEXT PRIMARY KEY,
                doc JSONB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS escales_milestones (
                id TEXT PRIMARY KEY,
                doc JSONB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS escales_audit (
                id BIGSERIAL PRIMARY KEY,
                doc JSONB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS escales_finance (
                id TEXT PRIMARY KEY,
                at TEXT NOT NULL,
                doc JSONB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS escales_webhooks (
                id TEXT PRIMARY KEY,
                doc JSONB NOT NULL
            );
            """
        )

    def _load(self, table: str, doc_id: str) -> Optional[dict]:
        row = self._conn.execute(
            f"SELECT doc FROM {table} WHERE id = %s",
            (doc_id,),
        ).fetchone()
        if row is None:
            return None
        return copy.deepcopy(dict(row[0]))

    def _save_doc(self, table: str, doc: dict) -> dict:
        stored = copy.deepcopy(doc)
        self._conn.execute(
            f"""
            INSERT INTO {table} (id, doc) VALUES (%s, %s::jsonb)
            ON CONFLICT (id) DO UPDATE SET doc = EXCLUDED.doc
            """,
            (stored["_id"], json.dumps(stored)),
        )
        return copy.deepcopy(stored)

    async def insert_pledge_once(self, doc: dict) -> dict:
        with self._lock:
            key = doc.get("client_key")
            if key:
                row = self._conn.execute(
                    "SELECT doc FROM escales_pledges WHERE doc->>'client_key' = %s",
                    (key,),
                ).fetchone()
                if row is not None:
                    return copy.deepcopy(dict(row[0]))
            return self._save_doc("escales_pledges", doc)

    async def save_pledge(self, doc: dict) -> dict:
        with self._lock:
            return self._save_doc("escales_pledges", doc)

    async def get_pledge(self, pledge_id: str) -> Optional[dict]:
        with self._lock:
            return self._load("escales_pledges", pledge_id)

    async def find_by_client_key(self, client_key: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT doc FROM escales_pledges WHERE doc->>'client_key' = %s",
                (client_key,),
            ).fetchone()
            return copy.deepcopy(dict(row[0])) if row else None

    async def find_pledge_by_order_id(self, order_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT doc FROM escales_pledges WHERE doc->>'order_id' = %s",
                (order_id,),
            ).fetchone()
            return copy.deepcopy(dict(row[0])) if row else None

    async def find_pledge_by_authorization_id(self, authorization_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT doc FROM escales_pledges WHERE doc->>'authorization_id' = %s",
                (authorization_id,),
            ).fetchone()
            return copy.deepcopy(dict(row[0])) if row else None

    async def list_pledges(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT doc FROM escales_pledges ORDER BY doc->>'_id'").fetchall()
            return [copy.deepcopy(dict(row[0])) for row in rows]

    async def list_pledges_for_milestone(self, milestone_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT doc FROM escales_pledges WHERE doc->>'milestone_id' = %s",
                (milestone_id,),
            ).fetchall()
            return [copy.deepcopy(dict(row[0])) for row in rows]

    async def append_evidence(self, milestone_id: str, evidence: dict) -> dict:
        with self._lock:
            doc = self._load("escales_milestones", milestone_id) or {
                "_id": milestone_id,
                "evidence": [],
                "proposal": None,
                "updated_at": evidence.get("recorded_at"),
            }
            doc["evidence"] = list(doc.get("evidence") or []) + [copy.deepcopy(evidence)]
            doc["updated_at"] = evidence.get("recorded_at")
            self._save_doc("escales_milestones", doc)
            return copy.deepcopy(evidence)

    async def get_milestone(self, milestone_id: str) -> Optional[dict]:
        with self._lock:
            return self._load("escales_milestones", milestone_id)

    async def ensure_milestone(self, milestone_id: str, meta: Optional[dict] = None) -> dict:
        with self._lock:
            doc = self._load("escales_milestones", milestone_id)
            if doc is None:
                doc = {
                    "_id": milestone_id,
                    "evidence": [],
                    "proposal": None,
                    "meta": copy.deepcopy(meta or {}),
                    "updated_at": now_iso(),
                }
            elif meta:
                doc["meta"] = {**(doc.get("meta") or {}), **copy.deepcopy(meta)}
                doc["updated_at"] = now_iso()
            return self._save_doc("escales_milestones", doc)

    async def list_milestones(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT doc FROM escales_milestones").fetchall()
            return [copy.deepcopy(dict(row[0])) for row in rows]

    async def set_proposal(self, milestone_id: str, proposal: dict) -> dict:
        with self._lock:
            doc = self._load("escales_milestones", milestone_id) or {
                "_id": milestone_id,
                "evidence": [],
                "proposal": None,
                "updated_at": now_iso(),
            }
            doc["proposal"] = copy.deepcopy(proposal)
            doc["updated_at"] = proposal.get("at") or now_iso()
            return self._save_doc("escales_milestones", doc)

    async def append_audit(self, entry: dict) -> dict:
        with self._lock:
            stored = copy.deepcopy(entry)
            self._conn.execute(
                "INSERT INTO escales_audit (doc) VALUES (%s::jsonb)",
                (json.dumps(stored),),
            )
            return copy.deepcopy(stored)

    async def list_audit(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT doc FROM escales_audit ORDER BY id").fetchall()
            return [copy.deepcopy(dict(row[0])) for row in rows]

    async def append_finance(self, entry: dict) -> dict:
        with self._lock:
            stored = copy.deepcopy(entry)
            self._conn.execute(
                """
                INSERT INTO escales_finance (id, at, doc) VALUES (%s, %s, %s::jsonb)
                ON CONFLICT (id) DO UPDATE SET at = EXCLUDED.at, doc = EXCLUDED.doc
                """,
                (stored["_id"], stored.get("at") or "", json.dumps(stored)),
            )
            return copy.deepcopy(stored)

    async def list_finance(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT doc FROM escales_finance ORDER BY at, id"
            ).fetchall()
            return [copy.deepcopy(dict(row[0])) for row in rows]

    async def has_webhook(self, transmission_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM escales_webhooks WHERE id = %s",
                (transmission_id,),
            ).fetchone()
            return row is not None

    async def claim_webhook(self, transmission_id: str, meta: dict) -> bool:
        with self._lock:
            stored = {"_id": transmission_id, "at": now_iso(), **meta}
            cur = self._conn.execute(
                """
                INSERT INTO escales_webhooks (id, doc) VALUES (%s, %s::jsonb)
                ON CONFLICT (id) DO NOTHING
                """,
                (transmission_id, json.dumps(stored)),
            )
            return cur.rowcount == 1
