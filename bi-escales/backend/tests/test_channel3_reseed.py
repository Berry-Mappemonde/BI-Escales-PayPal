"""C3-APP-A2 merged seed counts, needs_confirmation, and stale wishlist lines."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.channel3_catalog import get_catalog_item, load_catalog_seed
from app.channel3_wishlist_store import reset_wishlist_store
from app.routers.escales import router, set_paypal_client_factory

ADMIN = "test-admin-key"
USD_SAMPLE = "QE0Vp6a"
REMOVED = "hwD0sF9"
LIFERAFT_UNCONFIRMED = "k4nWRDl"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", ADMIN)
    monkeypatch.setenv("ESCALES_CHANNEL3_ENABLED", "1")
    monkeypatch.setenv("ESCALES_WISHLISTS_ENABLED", "1")
    reset_wishlist_store()
    set_paypal_client_factory(lambda: object())
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client
    set_paypal_client_factory(None)


def test_seed_metadata_and_minor_units():
    payload = load_catalog_seed()
    assert payload["item_count"] == 52
    raw = Path(__file__).resolve().parents[1] / "static" / "channel3-catalogue.seed.json"
    meta = __import__("json").loads(raw.read_text(encoding="utf-8"))
    assert meta.get("from_c3_02_count") == 9
    assert meta.get("from_c3_02b_count") == 43
    item = get_catalog_item(USD_SAMPLE)
    assert item is not None
    assert item["price_currency"] == "USD"
    assert item["unit_price_amount_minor"] == 3999


def test_public_catalog_excludes_needs_confirmation(api):
    res = api.get("/api/escales/channel3/catalog")
    assert res.status_code == 200
    body = res.json()
    assert body["item_count"] == 50
    assert body["seed_item_count"] == 52
    ids = {i["channel3_product_id"] for i in body["items"]}
    assert LIFERAFT_UNCONFIRMED not in ids
    assert "60BXA1O" not in ids
    assert all(
        str(i.get("catalog_status") or "").casefold() != "needs_confirmation" for i in body["items"]
    )


def test_removed_and_unconfirmed_return_404(api):
    assert api.get(f"/api/escales/channel3/catalog/{REMOVED}").status_code == 404
    assert api.get(f"/api/escales/channel3/catalog/{LIFERAFT_UNCONFIRMED}").status_code == 404
    internal = get_catalog_item(LIFERAFT_UNCONFIRMED, include_needs_confirmation=True)
    assert internal is not None
    assert internal.get("catalog_status") == "needs_confirmation"


def test_stale_wishlist_line_flagged_without_500(api):
    create = api.post(
        "/api/escales/treasurer/wishlists",
        headers={"x-admin-key": ADMIN},
        json={
            "title": "Stale",
            "slug": "stale-lines",
            "items": [{"channel3_product_id": REMOVED, "quantity": 1}],
        },
    )
    assert create.status_code == 400
    wid = api.post(
        "/api/escales/treasurer/wishlists",
        headers={"x-admin-key": ADMIN},
        json={"title": "Good", "slug": "good-lines", "items": []},
    ).json()["_id"]
    api.post(
        f"/api/escales/treasurer/wishlists/{wid}/items",
        headers={"x-admin-key": ADMIN},
        json={"channel3_product_id": USD_SAMPLE, "quantity": 1},
    )
    store = __import__("app.channel3_wishlist_store", fromlist=["get_wishlist_store"]).get_wishlist_store()

    async def _inject_removed():
        row = await store.get_wishlist(wid)
        row["items"].append({"channel3_product_id": REMOVED, "quantity": 1, "project_id": "gear-c3-removed"})
        await store.save_wishlist(row)

    import asyncio

    asyncio.run(_inject_removed())
    api.post(
        f"/api/escales/treasurer/wishlists/{wid}/publish",
        headers={"x-admin-key": ADMIN},
        json={"published": True},
    )
    public = api.get(f"/api/escales/wishlists/{wid}")
    assert public.status_code == 200
    flagged = [i for i in public.json()["items"] if i.get("catalog_available") is False]
    assert len(flagged) == 1
    assert flagged[0]["unavailable_reason"] == "removed_from_catalog"
    assert flagged[0]["channel3_product_id"] == REMOVED


def test_cannot_add_needs_confirmation_to_wishlist(api):
    create = api.post(
        "/api/escales/treasurer/wishlists",
        headers={"x-admin-key": ADMIN},
        json={"title": "Raft", "slug": "raft-block", "items": []},
    )
    wid = create.json()["_id"]
    res = api.post(
        f"/api/escales/treasurer/wishlists/{wid}/items",
        headers={"x-admin-key": ADMIN},
        json={"channel3_product_id": LIFERAFT_UNCONFIRMED, "quantity": 1},
    )
    assert res.status_code == 400
    assert "confirmation" in res.json()["detail"].lower()


def test_unconfirmed_gear_project_fund_returns_404(api):
    for pid in ("gear-c3-k4nwrdl", "gear-c3-60bxa1o"):
        res = api.get(f"/api/escales/projects/{pid}/fund")
        assert res.status_code == 404, pid


def test_unconfirmed_project_pledge_rejected_no_order(api, monkeypatch):
    orders: list[dict] = []

    class _Spy:
        def create_capture_order(self, *args, **kwargs):
            orders.append(kwargs)
            return {"id": "ORD-X", "status": "CREATED", "links": []}

    set_paypal_client_factory(lambda: _Spy())
    res = api.post(
        "/api/escales/pledges",
        json={
            "amount_eur": "3845.99",
            "description": "Raft",
            "milestone_id": "",
            "kind": "project_pledge",
            "target_id": "gear-c3-k4nwrdl",
        },
    )
    set_paypal_client_factory(lambda: object())
    assert res.status_code == 422
    assert "needs confirmation" in res.text.lower() or "not available" in res.text.lower()
    assert not orders
