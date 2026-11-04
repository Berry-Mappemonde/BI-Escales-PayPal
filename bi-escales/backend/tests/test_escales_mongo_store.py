"""Mongo ledger against mongomock-motor. No real cluster, no secrets."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("motor")
pytest.importorskip("mongomock_motor")

from mongomock_motor import AsyncMongoMockClient

from app.escales.ledger import MongoLedger, get_ledger, record_finance, reset_ledger
from app.escales.pledges import create_pledge


@pytest.fixture
def mongo_store(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "mongo")
    monkeypatch.setenv("MONGO_URL", "mongodb://mongomock")
    monkeypatch.setenv("DB_NAME", "bi_escales_test")
    import app.db as dbmod

    client = AsyncMongoMockClient()
    dbmod._client = client
    reset_ledger()
    yield client
    reset_ledger()
    dbmod._client = None


class Spy:
    def __init__(self):
        self.n = 0

    def create_authorize_order(self, amount_eur, description, reference_id, idempotency_key=None):
        self.n += 1
        order_id = f"ORDER{self.n}"
        return {
            "id": order_id,
            "links": [{"rel": "approve", "href": f"https://sandbox.paypal.com/checkoutnow?token={order_id}"}],
        }


def test_import_does_not_build_a_client_when_mongo_url_is_unset(monkeypatch):
    monkeypatch.delenv("MONGO_URL", raising=False)
    import app.db as dbmod

    built = []

    class Boom:
        def __init__(self, *args, **kwargs):
            built.append(args)
            raise AssertionError("client constructed")

    monkeypatch.setattr(dbmod, "AsyncIOMotorClient", Boom)
    monkeypatch.delenv("DB_NAME", raising=False)
    dbmod._client = None
    assert dbmod.db_name() == "bi_escales"
    assert dbmod._client is None
    assert built == []
    with pytest.raises(RuntimeError, match="MONGO_URL is not set"):
        dbmod.get_client()
    assert dbmod._client is None
    assert built == []


def test_mongo_store_round_trip(mongo_store):
    async def body():
        ledger = get_ledger()
        assert isinstance(ledger, MongoLedger)

        spy = Spy()
        created = await create_pledge(
            amount_eur="20.00",
            description="20 milles",
            milestone_id="dep-mayotte",
            client=spy,
            client_key="mongo-1",
        )
        again = await create_pledge(
            amount_eur="20.00",
            description="20 milles",
            milestone_id="dep-mayotte",
            client=spy,
            client_key="mongo-1",
        )
        assert again["_id"] == created["_id"]
        assert spy.n == 1
        stored = await ledger.get_pledge(created["_id"])
        assert stored["order_id"] == "ORDER1"
        assert stored["milestone_id"] == "dep-mayotte"
        by_order = await ledger.find_pledge_by_order_id("ORDER1")
        assert by_order["_id"] == created["_id"]
        listed = await ledger.list_pledges_for_milestone("dep-mayotte")
        assert [doc["_id"] for doc in listed] == [created["_id"]]

        evidence = {"recorded_at": "2026-11-04T00:00:00+00:00", "distance_nm": 12}
        await ledger.append_evidence("dep-mayotte", evidence)
        milestone = await ledger.get_milestone("dep-mayotte")
        assert milestone["evidence"][-1]["distance_nm"] == 12
        proposal = await ledger.set_proposal(
            "dep-mayotte",
            {"action": "wait", "at": "2026-11-04T00:01:00+00:00"},
        )
        assert proposal["proposal"]["action"] == "wait"

        await ledger.append_audit({"at": "2026-11-04T00:02:00+00:00", "kind": "note"})
        audit = await ledger.list_audit()
        assert audit[-1]["kind"] == "note"

        finance = await record_finance("pledge_created", pledge_id=created["_id"], amount_eur="20.00")
        entries = await ledger.list_finance()
        assert any(entry["_id"] == finance["_id"] for entry in entries)

        assert await ledger.claim_webhook("tx-1", {"event": "test"}) is True
        assert await ledger.claim_webhook("tx-1", {"event": "test"}) is False
        assert await ledger.has_webhook("tx-1") is True

        saved = await mongo_store["bi_escales_test"]["escales_pledges"].find_one({"_id": created["_id"]})
        assert saved["client_key"] == "mongo-1"

    asyncio.run(body())
