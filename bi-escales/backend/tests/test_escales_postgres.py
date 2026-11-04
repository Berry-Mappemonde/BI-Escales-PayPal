"""Render Postgres ledger. Skips when no local database is reachable."""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.ledger import get_ledger, reset_ledger

DSN = os.environ.get("ESCALES_TEST_DATABASE_URL") or "dbname=postgres"


def _reachable() -> bool:
    try:
        import psycopg
    except ImportError:
        return False
    try:
        with psycopg.connect(DSN, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason="Postgres is not reachable")


@pytest.fixture
def pg(monkeypatch):
    monkeypatch.setenv("ESCALES_POSTGRES_ENABLED", "1")
    monkeypatch.setenv("DATABASE_URL", DSN)
    monkeypatch.setenv("ESCALES_STORE", "memory")
    reset_ledger()
    ledger = get_ledger()
    yield ledger
    reset_ledger()
    import psycopg

    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(
            "TRUNCATE escales_pledges, escales_milestones, escales_audit, escales_finance, escales_webhooks"
        )


def test_postgres_ledger_survives_a_new_process_handle(pg):
    async def body():
        milestone = f"dep-{uuid.uuid4().hex[:8]}"
        await pg.ensure_milestone(milestone, meta={"arrival_iso": "2026-11-14T00:00:00+00:00", "title": "Mayotte"})
        saved = await pg.save_pledge({
            "_id": uuid.uuid4().hex,
            "status": "authorized",
            "milestone_id": milestone,
            "amount_eur": "120.00",
            "order_id": "ORDER-PG",
            "authorization_id": "AUTH-PG",
            "client_key": f"key-{uuid.uuid4().hex}",
        })
        assert await pg.claim_webhook("evt-pg", {"event_type": "X"}) is True
        assert await pg.claim_webhook("evt-pg", {"event_type": "X"}) is False
        return saved["_id"], milestone

    pledge_id, milestone = asyncio.run(body())
    reset_ledger()
    again = get_ledger()
    found = asyncio.run(again.get_pledge(pledge_id))
    assert found["status"] == "authorized"
    assert found["milestone_id"] == milestone
    assert asyncio.run(again.find_pledge_by_order_id("ORDER-PG"))["_id"] == pledge_id
    assert asyncio.run(again.has_webhook("evt-pg")) is True


def test_flag_off_keeps_memory(monkeypatch):
    monkeypatch.delenv("ESCALES_POSTGRES_ENABLED", raising=False)
    monkeypatch.setenv("ESCALES_STORE", "memory")
    reset_ledger()
    ledger = get_ledger()
    assert ledger.__class__.__name__ == "MemoryLedger"
    reset_ledger()
