"""Channel3 onboard gear — POST https://api.trychannel3.com/v1/search (mocked in unit tests)."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.channel3_client import CHANNEL3_SEARCH_URL, normalize_product, search_gear
from app.escales.pledges import reset_ledger
from app.routers.escales import router, set_paypal_client_factory


class FakePayPal:
    def create_authorize_order(self, *args, **kwargs):
        return {"id": "ORDER1", "links": [{"rel": "approve", "href": "https://example/approve"}]}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin-key")
    reset_ledger()
    set_paypal_client_factory(lambda: FakePayPal())
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client, None
    set_paypal_client_factory(None)
    reset_ledger()


def test_normalize_product_maps_offer_price():
    row = normalize_product(
        {
            "id": "prod-1",
            "title": "Life jacket",
            "images": ["https://img.example/jacket.jpg"],
            "offers": [{"url": "https://shop.example/jacket", "price": {"price": 49.9, "currency": "EUR"}}],
        },
        query="sailing life jacket",
    )
    assert row
    assert row["amount_eur"] == "49.90"
    assert row["buy_url"].startswith("https://")


def test_gear_route_hidden_without_flag(api, monkeypatch):
    client, _fake = api
    monkeypatch.delenv("ESCALES_CHANNEL3_ENABLED", raising=False)
    monkeypatch.delenv("CHANNEL3_API_KEY", raising=False)
    denied = client.get("/api/escales/channel3/gear")
    assert denied.status_code == 404


def test_gear_route_calls_channel3_with_mock(api, monkeypatch):
    client, _fake = api
    monkeypatch.setenv("ESCALES_CHANNEL3_ENABLED", "1")
    monkeypatch.setenv("CHANNEL3_API_KEY", "test-key-not-real")

    async def fake_search(**kwargs):
        return [
            {
                "id": "prod-1",
                "title": "Chart",
                "amount_eur": "12.00",
                "currency": "EUR",
                "buy_url": "https://shop.example/chart",
                "query": "nautical chart",
            }
        ]

    monkeypatch.setattr("app.routers.escales.search_gear", fake_search)
    res = client.get("/api/escales/channel3/gear")
    assert res.status_code == 200
    assert res.json()["items"][0]["title"] == "Chart"


def test_search_gear_uses_http_client(monkeypatch):
    async def run():
        monkeypatch.setenv("CHANNEL3_API_KEY", "unit-test-key")
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = {
            "products": [
                {
                    "id": "p1",
                    "title": "Flashlight",
                    "offers": [{"url": "https://x/y", "price": {"price": 10, "currency": "EUR"}}],
                }
            ]
        }
        client = AsyncMock()
        client.post.return_value = response
        rows = await search_gear(queries=("marine LED flashlight",), client=client, limit=1)
        assert rows[0]["title"] == "Flashlight"
        client.post.assert_awaited()
        assert client.post.await_args.args[0] == CHANNEL3_SEARCH_URL
        await client.aclose()

    asyncio.run(run())


@pytest.mark.skipif(not os.environ.get("CHANNEL3_API_KEY"), reason="CHANNEL3_API_KEY not set")
def test_live_channel3_search():
    rows = asyncio.run(search_gear(queries=("sailing life jacket",), limit=1))
    assert rows, "expected at least one product from live Channel3 search"
