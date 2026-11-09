from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.expedition_cart import build_expedition_cart
from app.routers.escales import router, set_paypal_client_factory


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    set_paypal_client_factory(lambda: object())
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client
    set_paypal_client_factory(None)


def test_expedition_cart_has_six_gear_and_sixty_one_marinas():
    cart = asyncio.run(build_expedition_cart("fr"))
    assert cart["gear_count"] == 6
    assert cart["marina_count"] == 61
    lines = cart["lines"]
    assert len(lines) == 67
    gear = [row for row in lines if row["kind"] == "gear"]
    marinas = [row for row in lines if row["kind"] == "marina"]
    assert len(gear) == 6
    assert len(marinas) == 61
    assert all(row.get("amount_eur") or row.get("price_label") for row in lines)


def test_expedition_cart_price_unavailable_label_en():
    cart = asyncio.run(build_expedition_cart("en"))
    gear = [row for row in cart["lines"] if row["kind"] == "gear"]
    assert any(row.get("amount_eur") for row in gear)
    # Dive computer seed keeps sandbox goal even without catalogue product URL.
    dive = next(row for row in gear if row["id"] == "gear-dive-computer-expedition")
    assert dive["amount_eur"] == "450.00"


def test_expedition_cart_route(api):
    fr = api.get("/api/escales/expedition/cart?lang=fr")
    assert fr.status_code == 200
    body = fr.json()
    assert body["gear_count"] == 6
    assert body["marina_count"] == 61
    en = api.get("/api/escales/expedition/cart?lang=en")
    assert en.status_code == 200
    assert "price unavailable" not in str(en.json())
