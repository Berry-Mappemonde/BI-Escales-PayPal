"""Clément-approved test2 follow-up (live findings on test2)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bi_marinas_catalog import geojson_collection_source, mooring_marinas_to_geojson
from app.escales.captain import resolve_chat_lang
from app.escales.pledges import reset_ledger
from app.routers.escales import router, set_paypal_client_factory


@pytest.fixture(autouse=True)
def memory_env(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test2-lot")
    reset_ledger()
    yield
    reset_ledger()
    set_paypal_client_factory(None)


def test_chat_lang_inferred_from_english_message_when_lang_omitted():
    text = "Show me the PayPal transactions for the treasurer"
    assert resolve_chat_lang(text, requested=None) == "en"


def test_treasurer_readonly_chat_english_without_lang_and_nim_label():
    spy = type("C", (), {
        "get_order": lambda self, oid: {"id": oid},
        "get_authorization": lambda self, aid: {"id": aid},
        "list_disputes": lambda self, **k: {"items": []},
        "search_transactions": lambda self, **k: {"transaction_details": [{"id": "T1"}]},
        "list_invoices": lambda self, **k: {"items": []},
    })()
    set_paypal_client_factory(lambda: spy)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    body = client.post(
        "/api/escales/captain/chat",
        json={"message": "List recent PayPal transactions for the treasurer"},
        headers={"x-admin-key": "test2-lot", "Accept-Language": "fr-FR,fr;q=0.9"},
    ).json()
    assert "PayPal transactions" in body["reply"]
    assert "Transactions PayPal" not in body["reply"]
    assert body["model_source"] == "paypal_readonly_tools"
    assert body.get("model_label", "").startswith("NVIDIA NIM")
    tools = body.get("paypal_tools") or {}
    assert "transactions.search" in tools.get("called", [])
    assert "transactions.search" in tools.get("tools", [])


def test_geojson_collection_source_atlas_vs_bundled():
    assert geojson_collection_source([{"source": "bundled"}]) == "bundled"
    assert geojson_collection_source([{"source": "bi_export"}]) == "bundled"
    assert geojson_collection_source([{"source": "atlas"}]) == "atlas"


def test_escale_marinas_geojson_without_name_returns_all_stops(monkeypatch):
    from app import main as main_module

    async def fake_all(client=None):
        return {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {"osm_id": "way/1"}}],
            "source": "bundled",
        }

    monkeypatch.setattr(main_module, "get_all_escale_marinas_geojson", fake_all)
    client = TestClient(main_module.app)
    res = client.get("/api/escale-marinas.geojson")
    assert res.status_code == 200
    payload = res.json()
    assert payload["type"] == "FeatureCollection"
    assert payload.get("source") == "bundled"
    assert len(payload.get("features") or []) >= 1


def test_single_stop_geojson_has_top_level_source():
    fc = mooring_marinas_to_geojson([{"name": "M", "lat": 1.0, "lon": 2.0, "osm_id": "way/x"}])
    assert fc.get("source") == "bundled"
