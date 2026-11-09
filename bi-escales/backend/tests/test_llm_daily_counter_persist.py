"""Mongo-backed LLM daily counter (UTC keys, in-memory fallback)."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import llm
from app.core import llm_daily_counter_store as store


@pytest.fixture
def mongo_counter_db(monkeypatch):
    pytest.importorskip("mongomock_motor")
    from mongomock_motor import AsyncMongoMockClient

    import app.db as dbmod

    monkeypatch.setenv("MONGO_URL", "mongodb://mongomock")
    monkeypatch.setenv("DB_NAME", "bi_escales_llm_counter_test")
    monkeypatch.setenv("ESCALES_ENV", "production")
    monkeypatch.delenv("ESCALES_RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.setenv("ESCALES_LLM_DAILY_CAP", "100")
    client = AsyncMongoMockClient()
    dbmod._client = client
    llm.reset_llm_budget()
    yield client[dbmod.db_name()][store.collection_name()]
    llm.reset_llm_budget()
    dbmod._client = None


async def _coll_find_one(coll, query):
    return await coll.find_one(query)


def test_persisted_counter_survives_process_restart(monkeypatch, mongo_counter_db):
    day = dt.datetime(2026, 11, 9, 15, 0, tzinfo=dt.timezone.utc)

    async def warm():
        for _ in range(3):
            assert await llm.consume_llm_call(day) is True
        assert await llm.fetch_llm_calls_today(day) == 3

    asyncio.run(warm())
    llm.reset_llm_budget()
    assert llm.llm_calls_today() == 0

    async def after_restart():
        assert await llm.fetch_llm_calls_today(day) == 3
        assert await llm.consume_llm_call(day) is True
        assert await llm.fetch_llm_calls_today(day) == 4

    asyncio.run(after_restart())
    doc = asyncio.run(_coll_find_one(mongo_counter_db, {"_id": day.date().isoformat()}))
    assert doc["count"] == 4
    assert doc["name"] == store.counter_name()


def test_concurrent_increments_are_atomic(mongo_counter_db):
    day = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.timezone.utc)

    async def body():
        results = await asyncio.gather(*(llm.consume_llm_call(day) for _ in range(20)))
        assert all(results)
        assert await llm.fetch_llm_calls_today(day) == 20
        return results

    asyncio.run(body())
    doc = asyncio.run(_coll_find_one(mongo_counter_db, {"_id": day.date().isoformat()}))
    assert doc["count"] == 20


def test_utc_midnight_uses_a_fresh_date_key(mongo_counter_db):
    late = dt.datetime(2026, 11, 9, 23, 59, tzinfo=dt.timezone.utc)
    early = dt.datetime(2026, 11, 10, 0, 0, tzinfo=dt.timezone.utc)

    async def body():
        assert await llm.consume_llm_call(late) is True
        assert await llm.fetch_llm_calls_today(late) == 1
        assert await llm.consume_llm_call(early) is True
        assert await llm.fetch_llm_calls_today(early) == 1

    asyncio.run(body())
    d1 = asyncio.run(_coll_find_one(mongo_counter_db, {"_id": "2026-11-09"}))
    d2 = asyncio.run(_coll_find_one(mongo_counter_db, {"_id": "2026-11-10"}))
    assert d1["count"] == 1
    assert d2["count"] == 1


def test_mongo_error_falls_back_and_logs_once(caplog, monkeypatch):
    monkeypatch.setenv("MONGO_URL", "mongodb://mongomock")
    monkeypatch.setenv("ESCALES_ENV", "production")
    monkeypatch.delenv("ESCALES_RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.setenv("ESCALES_LLM_DAILY_CAP", "5")
    llm.reset_llm_budget()

    async def fail_consume(*_a, **_k):
        store._warn_storage_once(RuntimeError("mongo down"))
        return None

    monkeypatch.setattr(store, "consume_one", fail_consume)

    caplog.set_level(logging.WARNING, logger="escales.llm")

    async def body():
        for _ in range(3):
            assert await llm.consume_llm_call() is True
        assert llm.llm_calls_today() == 3

    asyncio.run(body())
    warnings = [r for r in caplog.records if "in-memory fallback" in r.message]
    assert len(warnings) == 1
