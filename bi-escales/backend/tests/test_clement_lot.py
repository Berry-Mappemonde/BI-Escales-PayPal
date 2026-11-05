"""Clément lot: masked keys UI, captain FR detection, marinas legend (backend slice)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.captain import message_lang, resolve_chat_lang
from app.escales.pledges import reset_ledger
from app.routers.escales import router, set_paypal_client_factory


@pytest.fixture(autouse=True)
def memory_env(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "clement-lot")
    reset_ledger()
    yield
    reset_ledger()
    set_paypal_client_factory(None)


def test_message_lang_french_treasurer_phrase():
    assert message_lang("liste mes transactions sandbox") == "fr"


def test_resolve_chat_lang_explicit_lang_still_wins():
    assert resolve_chat_lang("liste mes transactions sandbox", requested="en") == "en"


def test_treasurer_chat_french_without_lang_uses_french_reply():
    spy = type("C", (), {
        "get_order": lambda self, oid: {"id": oid},
        "get_authorization": lambda self, aid: {"id": aid},
        "list_disputes": lambda self, **k: {"items": []},
        "search_transactions": lambda self, **k: {"transaction_details": []},
        "list_invoices": lambda self, **k: {"items": []},
    })()
    set_paypal_client_factory(lambda: spy)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    body = client.post(
        "/api/escales/captain/chat",
        json={"message": "liste mes transactions sandbox"},
        headers={"x-admin-key": "clement-lot", "Accept-Language": "en-US,en;q=0.9"},
    ).json()
    assert "Transactions PayPal" in body["reply"] or "lecture seule" in body["reply"]
    assert "PayPal transactions from" not in body["reply"]


def test_treasurer_chat_english_without_lang_stays_english():
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
        json={"message": "Show me the PayPal transactions for the treasurer"},
        headers={"x-admin-key": "clement-lot", "Accept-Language": "fr-FR,fr;q=0.9"},
    ).json()
    assert "PayPal transactions" in body["reply"]
    assert body.get("paypal_tools", {}).get("called") == ["transactions.search"]
