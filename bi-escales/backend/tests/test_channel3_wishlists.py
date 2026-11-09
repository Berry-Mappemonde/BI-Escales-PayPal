"""Wishlist CRUD, publish visibility, buy-link policy, multicurrency funding."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.channel3_catalog import get_catalog_item, project_id_for_product
from app.channel3_public import CHANNEL3_BUY_DISCLOSURE
from app.channel3_wishlist_store import reset_wishlist_store
from app.escales.ledger import record_finance, reset_ledger
from app.routers.escales import router, set_paypal_client_factory

ADMIN = "test-admin-key"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", ADMIN)
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


def _treasurer_headers():
    return {"x-admin-key": ADMIN}


def test_catalog_public_count_and_no_optional_clothing(api):
    res = api.get("/api/escales/channel3/catalog")
    assert res.status_code == 200
    body = res.json()
    assert body["item_count"] == 50
    assert body["seed_item_count"] == 52
    optional = [i for i in body["items"] if i.get("catalog_optional")]
    assert optional == []
    assert "channel3_buy_url" not in body["items"][0]


def test_wishlist_publish_visibility(api):
    create = api.post(
        "/api/escales/treasurer/wishlists",
        headers=_treasurer_headers(),
        json={"title": "Deck", "slug": "deck-gear", "items": []},
    )
    assert create.status_code == 200
    wid = create.json()["_id"]
    item = get_catalog_item("QE0Vp6a")
    add = api.post(
        f"/api/escales/treasurer/wishlists/{wid}/items",
        headers=_treasurer_headers(),
        json={"channel3_product_id": "QE0Vp6a", "quantity": item["quantity_needed"]},
    )
    assert add.status_code == 200
    assert api.get(f"/api/escales/wishlists/{wid}").status_code == 404
    pub = api.post(
        f"/api/escales/treasurer/wishlists/{wid}/publish",
        headers=_treasurer_headers(),
        json={"published": True},
    )
    assert pub.status_code == 200
    public = api.get(f"/api/escales/wishlists/{wid}")
    assert public.status_code == 200
    assert public.json()["published"] is True


def test_usd_item_eur_funding_not_supported(api):
    res = api.get("/api/escales/channel3/catalog/QE0Vp6a")
    assert res.status_code == 200
    body = res.json()
    assert body["price_currency"] == "USD"
    assert body["paypal_currency_supported"] is True
    assert body["funded_currency"] == "USD"
    assert body.get("funded_pct") == 0


def test_buy_link_shown_only_when_fully_funded(api):
    pid = project_id_for_product("QE0Vp6a")
    before = api.get(f"/api/escales/channel3/catalog/by-project/{pid}/fund")
    assert before.status_code == 200
    assert "channel3_buy_url" not in before.json()

    async def _seed_capture():
        await record_finance(
            "pledge_captured",
            amount_eur="9999.00",
            milestone_id="projet",
            target_id=pid,
            pledge_kind="project_pledge",
        )

    asyncio.run(_seed_capture())
    # USD target — EUR pledges still cannot reach 100%
    after = api.get(f"/api/escales/channel3/catalog/by-project/{pid}/fund")
    assert "channel3_buy_url" not in after.json()


def test_eur_item_buy_link_with_disclosure_when_funded(api):
    eur_items = [i for i in api.get("/api/escales/channel3/catalog").json()["items"] if i["price_currency"] == "EUR"]
    assert eur_items
    item = eur_items[0]
    pid = item["project_id"]
    target_minor = item["target_amount_minor"]

    async def _seed():
        await record_finance(
            "pledge_captured",
            amount_eur=f"{target_minor / 100:.2f}",
            milestone_id="projet",
            target_id=pid,
            pledge_kind="project_pledge",
        )

    asyncio.run(_seed())
    body = api.get(f"/api/escales/projects/{pid}/fund").json()
    assert body.get("fully_funded") is True
    assert body.get("channel3_buy_url")
    assert body.get("channel3_buy_disclosure") == CHANNEL3_BUY_DISCLOSURE


def test_wishlist_line_quantity_sets_default_target(api):
    create = api.post(
        "/api/escales/treasurer/wishlists",
        headers=_treasurer_headers(),
        json={"title": "Qty", "slug": "qty-test", "items": []},
    )
    wid = create.json()["_id"]
    add = api.post(
        f"/api/escales/treasurer/wishlists/{wid}/items",
        headers=_treasurer_headers(),
        json={"channel3_product_id": "QE0Vp6a", "quantity": 2},
    )
    assert add.status_code == 200
    line = add.json()["items"][0]
    assert line["quantity"] == 2
    assert line["unit_price_amount_minor"] == 3999
    assert line["target_amount_minor"] == 7998


def test_wishlist_explicit_target_preserved(api):
    create = api.post(
        "/api/escales/treasurer/wishlists",
        headers=_treasurer_headers(),
        json={"title": "Target", "slug": "target-test", "items": []},
    )
    wid = create.json()["_id"]
    add = api.post(
        f"/api/escales/treasurer/wishlists/{wid}/items",
        headers=_treasurer_headers(),
        json={"channel3_product_id": "QE0Vp6a", "quantity": 2, "target_amount_minor": 1500},
    )
    assert add.status_code == 200
    line = add.json()["items"][0]
    assert line["target_amount_minor"] == 1500
    assert line["quantity"] == 2


def test_public_wishlist_item_shows_line_quantity(api):
    create = api.post(
        "/api/escales/treasurer/wishlists",
        headers=_treasurer_headers(),
        json={"title": "Public qty", "slug": "public-qty", "items": []},
    )
    wid = create.json()["_id"]
    api.post(
        f"/api/escales/treasurer/wishlists/{wid}/items",
        headers=_treasurer_headers(),
        json={"channel3_product_id": "QE0Vp6a", "quantity": 2},
    )
    api.post(
        f"/api/escales/treasurer/wishlists/{wid}/publish",
        headers=_treasurer_headers(),
        json={"published": True},
    )
    body = api.get(f"/api/escales/wishlists/{wid}").json()
    item = body["items"][0]
    assert item["quantity"] == 2
    assert item["quantity_needed"] == 2
    assert item["target_amount_minor"] == 7998


def test_flags_off_returns_404(api, monkeypatch):
    monkeypatch.setenv("ESCALES_WISHLISTS_ENABLED", "")
    res = api.get("/api/escales/channel3/catalog")
    assert res.status_code == 404
