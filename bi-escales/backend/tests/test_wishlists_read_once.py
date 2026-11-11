"""A12: the public wishlist and catalogue read the finance journal once, not twice per item.

On the hosted demo each journal read is a database round trip of about 0.23 s; 50 items
times two reads was the 23 s the wishlist page spent on "Loading". The totals must be the
same whether the journal is passed in or read by the function itself.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.channel3_catalog import get_catalog_item, list_catalog_items, project_id_for_product
from app.channel3_funding import fund_snapshot_for_project
from app.channel3_wishlist_store import reset_wishlist_store
from app.channel3_wishlists import public_catalog_payload, public_wishlist_payload
from app.escales import ledger as ledger_mod
from app.escales.ledger import list_finance_entries, record_finance, reset_ledger
from app.routers.escales import router, set_paypal_client_factory

ADMIN = {"x-admin-key": "test-admin-key"}
FUNDED = "QE0Vp6a"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin-key")
    monkeypatch.setenv("ESCALES_CHANNEL3_ENABLED", "1")
    monkeypatch.setenv("ESCALES_WISHLISTS_ENABLED", "1")
    reset_ledger()
    reset_wishlist_store()
    set_paypal_client_factory(lambda: object())
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client
    set_paypal_client_factory(None)
    reset_ledger()
    reset_wishlist_store()


@pytest.fixture
def reads(monkeypatch):
    """Counts the reads of the finance journal on the active ledger."""
    store = ledger_mod.get_ledger()
    original = store.list_finance
    count = {"finance": 0}

    async def counted():
        count["finance"] += 1
        return await original()

    monkeypatch.setattr(store, "list_finance", counted)
    return count


def _donate(product_id: str, amount: str, kind: str = "pledge_captured") -> None:
    item = get_catalog_item(product_id)
    asyncio.run(
        record_finance(
            kind,
            amount_eur=amount,
            currency=str(item["price_currency"]),
            milestone_id="projet",
            target_id=project_id_for_product(product_id),
            pledge_kind="project_pledge",
        )
    )


def _publish_everything(api) -> str:
    created = api.post("/api/escales/treasurer/wishlists", headers=ADMIN, json={"title": "Crew of six", "slug": "crew", "items": []})
    assert created.status_code == 200, created.text
    wid = created.json()["_id"]
    for row in list_catalog_items(public_only=True):
        added = api.post(
            f"/api/escales/treasurer/wishlists/{wid}/items",
            headers=ADMIN,
            json={"channel3_product_id": row["channel3_product_id"], "quantity": 1},
        )
        assert added.status_code == 200, added.text
    assert api.post(f"/api/escales/treasurer/wishlists/{wid}/publish", headers=ADMIN, json={"published": True}).status_code == 200
    return wid


def test_public_wishlists_read_the_journal_once_for_fifty_lines(api, reads):
    _publish_everything(api)
    _donate(FUNDED, "5.00")
    reads["finance"] = 0
    body = api.get("/api/escales/wishlists").json()
    assert len(body["wishlists"][0]["items"]) == 50
    assert reads["finance"] == 1


def test_two_published_lists_still_cost_one_read(api, reads):
    _publish_everything(api)
    second = api.post("/api/escales/treasurer/wishlists", headers=ADMIN, json={"title": "Deck", "slug": "deck", "items": []}).json()["_id"]
    api.post(f"/api/escales/treasurer/wishlists/{second}/items", headers=ADMIN, json={"channel3_product_id": FUNDED, "quantity": 1})
    api.post(f"/api/escales/treasurer/wishlists/{second}/publish", headers=ADMIN, json={"published": True})
    reads["finance"] = 0
    assert len(api.get("/api/escales/wishlists").json()["wishlists"]) == 2
    assert reads["finance"] == 1


def test_no_published_list_costs_no_read(api, reads):
    assert api.get("/api/escales/wishlists").json() == {"wishlists": []}
    assert reads["finance"] == 0


def test_one_public_wishlist_reads_the_journal_once(api, reads):
    wid = _publish_everything(api)
    reads["finance"] = 0
    assert api.get(f"/api/escales/wishlists/{wid}").status_code == 200
    assert reads["finance"] == 1


def test_public_catalogue_reads_the_journal_once(api, reads):
    reads["finance"] = 0
    assert api.get("/api/escales/channel3/catalog").json()["item_count"] == 50
    assert reads["finance"] == 1


def test_a_single_item_fund_reads_the_journal_once_not_twice(api, reads):
    project = project_id_for_product(FUNDED)
    reads["finance"] = 0
    asyncio.run(fund_snapshot_for_project(project))
    assert reads["finance"] == 1


def test_totals_are_the_same_with_or_without_the_shared_read(api):
    _publish_everything(api)
    _donate(FUNDED, "12.50")
    _donate(FUNDED, "7.50")
    _donate(FUNDED, "2.50", kind="pledge_refunded")
    other = list_catalog_items(public_only=True)[3]["channel3_product_id"]
    _donate(other, "4.00")

    async def both():
        journal = await list_finance_entries()
        for product in (FUNDED, other, list_catalog_items(public_only=True)[10]["channel3_product_id"]):
            project = project_id_for_product(product)
            assert await fund_snapshot_for_project(project, finance_entries=journal) == await fund_snapshot_for_project(project)
        shared = await public_catalog_payload()
        return shared

    catalogue = asyncio.run(both())
    funded = next(item for item in catalogue["items"] if item["channel3_product_id"] == FUNDED)
    currency = get_catalog_item(FUNDED)["price_currency"]
    assert funded["funded_currency"] == currency
    # 12.50 + 7.50 - 2.50 = 17.50 in the item's own currency.
    assert funded["funded_amount_minor"] == 1750
    untouched = next(item for item in catalogue["items"] if item["channel3_product_id"] not in (FUNDED, other))
    assert untouched["funded_amount_minor"] == 0


def test_a_donation_shows_on_the_next_read_nothing_is_cached(api):
    wid = _publish_everything(api)

    def funded() -> int:
        items = api.get(f"/api/escales/wishlists/{wid}").json()["items"]
        return next(item for item in items if item["channel3_product_id"] == FUNDED)["funded_amount_minor"]

    assert funded() == 0
    _donate(FUNDED, "3.00")
    assert funded() == 300
    _donate(FUNDED, "1.00")
    assert funded() == 400


def test_an_empty_shared_journal_is_used_and_not_read_again(api, reads):
    _donate(FUNDED, "9.00")
    reads["finance"] = 0
    snapshot = asyncio.run(fund_snapshot_for_project(project_id_for_product(FUNDED), finance_entries=[]))
    assert reads["finance"] == 0
    assert snapshot["donation_count"] == 0

    async def payload():
        return await public_wishlist_payload({"_id": "w", "items": [{"channel3_product_id": FUNDED, "quantity": 1}]}, finance_entries=[])

    assert asyncio.run(payload())["items"][0]["funded_amount_minor"] == 0
    assert reads["finance"] == 0
