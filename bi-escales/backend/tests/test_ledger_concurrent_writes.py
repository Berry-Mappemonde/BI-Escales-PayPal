"""B19: authorize and the order-approved webhook save the same pledge concurrently.

Both read the pledge while it is ``created``. Whichever saves last used to replace
the whole document, so the webhook could turn ``authorized`` back into ``created``
while PayPal held the money. The ledger now merges the two writes.
"""
from __future__ import annotations

import asyncio
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.ledger import MemoryLedger, merge_concurrent_pledge

BASE = {
    "_id": "P1",
    "status": "created",
    "amount_eur": "3.00",
    "order_id": "ORDER1",
    "authorization_id": None,
    "history": ["created"],
}
EVENT = {"transmission_id": "T1", "event_type": "CHECKOUT.ORDER.APPROVED", "outcome": "accepted"}


def _authorized(doc):
    out = copy.deepcopy(doc)
    out["status"] = "authorized"
    out["authorization_id"] = "AUTH1"
    out["authorization_expires_at"] = "2026-12-04T16:48:10Z"
    out["history"] = out["history"] + ["authorized"]
    return out


def _webhooked(doc):
    out = copy.deepcopy(doc)
    out["history"] = out["history"] + ["webhook_order_approved"]
    out["webhook_events"] = list(out.get("webhook_events") or []) + [EVENT]
    return out


async def _race(ledger, first, second):
    await ledger.insert_pledge_once(copy.deepcopy(BASE))
    a = await ledger.get_pledge("P1")
    b = await ledger.get_pledge("P1")
    await ledger.save_pledge(first(a))
    await ledger.save_pledge(second(b))
    return await ledger.get_pledge("P1")


def _mongo_ledger(monkeypatch):
    pytest.importorskip("motor")
    pytest.importorskip("mongomock_motor")
    from mongomock_motor import AsyncMongoMockClient

    import app.db as dbmod
    from app.escales.ledger import MongoLedger

    monkeypatch.setenv("MONGO_URL", "mongodb://mongomock")
    monkeypatch.setenv("DB_NAME", "bi_escales_test_b19")
    dbmod._client = AsyncMongoMockClient()
    return MongoLedger(dbmod.get_db())


@pytest.fixture(params=["memory", "mongo"])
def ledger(request, monkeypatch):
    if request.param == "memory":
        yield MemoryLedger()
        return
    led = _mongo_ledger(monkeypatch)
    yield led
    import app.db as dbmod

    dbmod._client = None


def test_webhook_saving_last_does_not_undo_authorize(ledger):
    final = asyncio.run(_race(ledger, _authorized, _webhooked))
    assert final["status"] == "authorized"
    assert final["authorization_id"] == "AUTH1"
    assert final["authorization_expires_at"] == "2026-12-04T16:48:10Z"
    assert final["history"] == ["created", "authorized", "webhook_order_approved"]
    assert [e["transmission_id"] for e in final["webhook_events"]] == ["T1"]


def test_authorize_saving_last_keeps_the_webhook_event(ledger):
    final = asyncio.run(_race(ledger, _webhooked, _authorized))
    assert final["status"] == "authorized"
    assert final["authorization_id"] == "AUTH1"
    assert final["history"] == ["created", "webhook_order_approved", "authorized"]
    assert [e["transmission_id"] for e in final["webhook_events"]] == ["T1"]


def test_sequential_saves_are_unchanged():
    stored = _authorized(BASE)
    incoming = copy.deepcopy(stored)
    incoming["status"] = "captured"
    incoming["capture_id"] = "CAP1"
    incoming["history"] = stored["history"] + ["captured"]
    assert merge_concurrent_pledge(stored, incoming) == incoming


def test_forward_moves_from_a_stale_copy_still_apply():
    stored = _authorized(BASE)
    incoming = copy.deepcopy(stored)
    incoming["status"] = "voided"
    incoming["history"] = stored["history"] + ["voided"]
    merged = merge_concurrent_pledge(stored, incoming)
    assert merged["status"] == "voided"


def test_same_webhook_twice_is_not_duplicated():
    stored = _webhooked(BASE)
    incoming = _webhooked(BASE)
    merged = merge_concurrent_pledge(stored, incoming)
    assert [e["transmission_id"] for e in merged["webhook_events"]] == ["T1"]


def test_new_pledge_without_stored_copy():
    assert merge_concurrent_pledge(None, BASE) is BASE
