"""Lot LANG: app UI language drives Escales API errors, PayPal payloads, and AI calls."""
from __future__ import annotations

import ast
import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales import captain
from app.escales.departure_clock import CAPTURE_RULES_FR
from app.escales.app_i18n import default_app_language, error_payload
from app.escales.paypal_reconcile import reconcile_note
from app.escales.config import EscalesConfig
from app.escales.paypal_client import PayPalClient, paypal_checkout_locale
from app.escales.paypal_disputes import dispute_evidence_notes
from app.escales.paypal_invoicing import create_partner_invoice, remind_invoice
from app.escales.paypal_reconcile import reconcile_paypal_ledger
from app.escales.paypal_subscriptions import (
    CREW_LABELS,
    approve_crew_subscription,
    create_crew_subscription,
    ensure_crew_supporter_catalog,
    resolve_crew_supporter_plan_id,
)
from app.escales.project_payouts import approve_project_payout, propose_project_payout
from app.escales.pledges import get_ledger, reset_ledger
from app.routers.escales import router, set_paypal_client_factory


@pytest.fixture(autouse=True)
def memory_env(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "lang-admin")
    reset_ledger()
    yield
    reset_ledger()
    set_paypal_client_factory(None)


def test_default_app_language_is_french():
    assert default_app_language() == "fr"


def test_error_payload_localizes_known_codes():
    fr = error_payload("paypal_not_configured", "fr")
    en = error_payload("paypal_not_configured", "en")
    assert fr["code"] == "paypal_not_configured"
    assert "bac à sable" in fr["detail"]
    assert "sandbox" in en["detail"].lower()


def test_as_http_returns_structured_detail_when_lang_set():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    res = client.post(
        "/api/escales/pledges",
        json={
            "amount_eur": "0",
            "description": "x",
            "milestone_id": "dep-dakar",
            "lang": "fr",
        },
    )
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert isinstance(detail, dict)
    assert detail.get("code") == "amount_invalid"


def test_post_chat_rate_limit_uses_app_lang_not_accept_language(monkeypatch):
    monkeypatch.setenv("ESCALES_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("ESCALES_CAPTAIN_RATE_PER_MINUTE", "1")
    from app.escales import rate_limit

    rate_limit.reset()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    payload = {"message": "Bonjour", "lang": "en"}
    headers = {"Accept-Language": "fr-FR,fr;q=0.9"}
    client.post("/api/escales/captain/chat", json=payload, headers=headers)
    res = client.post("/api/escales/captain/chat", json=payload, headers=headers)
    assert res.status_code == 429
    assert "Too many requests" in res.json()["detail"]


def test_n4_english_with_explicit_lang(monkeypatch):
    spy = type("C", (), {
        "get_order": lambda self, oid: {"id": oid},
        "get_authorization": lambda self, aid: {"id": aid},
        "list_disputes": lambda self, **k: {"items": []},
        "search_transactions": lambda self, **k: {"transaction_details": [{"x": 1}]},
        "list_invoices": lambda self, **k: {"items": []},
    })()
    set_paypal_client_factory(lambda: spy)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    body = client.post(
        "/api/escales/captain/chat",
        json={"message": "Show me the PayPal transactions for the treasurer", "lang": "en"},
        headers={"x-admin-key": "lang-admin", "Accept-Language": "fr-FR,fr;q=0.9"},
    ).json()
    assert "PayPal transactions" in body["reply"]
    assert "Litiges" not in body["reply"]


def test_treasurer_fr_transactions_use_readonly_tools(monkeypatch):
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
        json={"message": "Liste les transactions PayPal pour le trésorier", "lang": "fr"},
        headers={"x-admin-key": "lang-admin"},
    ).json()
    assert body["model_source"] == "paypal_readonly_tools"
    assert "Transactions PayPal" in body["reply"]
    assert "lecture seule" in body["reply"]


def test_project_pledge_min_amount_fr_422():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    res = client.post(
        "/api/escales/pledges",
        json={
            "amount_eur": "0.50",
            "description": "don",
            "kind": "project_pledge",
            "target_id": "projet",
            "lang": "fr",
        },
    )
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert detail["code"] == "project_pledge_min_amount"
    assert detail["detail"] == "Le don à un projet doit être d'au moins 1,00 €"


def test_reconcile_note_follows_lang():
    assert "Sandbox Transaction Search" in reconcile_note("en")
    assert "bac à sable" in reconcile_note("fr").lower()


def test_reconcile_route_passes_lang(monkeypatch):
    async def run():
        report = await reconcile_paypal_ledger(
            start_date="2099-06-01T00:00:00Z",
            end_date="2099-06-02T00:00:00Z",
            client=type("C", (), {"search_transactions": lambda self, **k: {"transaction_details": []}})(),
            finance_entries=[],
            lang="fr",
        )
        assert "bac à sable" in report["note"].lower()

    asyncio.run(run())
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    res = client.get(
        "/api/escales/paypal/reconcile",
        params={"start_date": "2099-06-01", "end_date": "2099-06-02", "lang": "fr"},
        headers={"x-admin-key": "lang-admin"},
    )
    assert res.status_code == 200
    assert "bac à sable" in res.json()["note"].lower()


def test_dispute_evidence_notes_french_default():
    async def run():
        text = await dispute_evidence_notes(milestone_id="missing-leg", lang="fr")
        assert "Aucune preuve" in text

    asyncio.run(run())


def test_paypal_client_subscription_locale_and_brand():
    calls = []

    def handler(request: httpx.Request):
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        if request.content:
            calls.append(json.loads(request.content.decode()))
        return httpx.Response(200, json={"id": "I-SUB", "links": []})

    client = PayPalClient(EscalesConfig("cid", "secret"), transport=httpx.MockTransport(handler))
    client.create_billing_subscription(
        plan_id="P-1",
        return_url="https://example.com/r",
        cancel_url="https://example.com/c",
        idempotency_key="k",
        locale=paypal_checkout_locale("fr"),
    )
    ctx = calls[-1]["application_context"]
    assert ctx["locale"] == "fr-FR"
    assert ctx["brand_name"] == "Berry-Mappemonde"


def test_crew_catalog_bilingual_labels():
    assert CREW_LABELS["fr"]["plan_name"] == "Soutien d'équipage (mensuel)"
    assert CREW_LABELS["en"]["plan_name"] == "Crew supporter (monthly)"


class CatalogSpy:
    products: list[dict] = []
    plans: list[dict] = []
    subscriptions: list[dict] = []

    def iter_billing_product_pages(self):
        yield {"products": self.products}

    def list_billing_plans(self, *, product_id: str, page_size: int = 20):
        return {"plans": [p for p in self.plans if p.get("product_id") == product_id]}

    def create_billing_product(self, *, name, description, idempotency_key):
        pid = f"PROD-{len(self.products)+1}"
        self.products.append({"id": pid, "name": name})
        return {"id": pid}

    def create_billing_plan(self, *, product_id, name, amount_eur, interval_unit, idempotency_key):
        plan_id = f"PLAN-{len(self.plans)+1}"
        self.plans.append({"id": plan_id, "name": name, "product_id": product_id})
        return {"id": plan_id}

    def create_billing_subscription(self, **kwargs):
        self.subscriptions.append(kwargs)
        return {"id": "I-NEW", "links": [{"rel": "approve", "href": "https://paypal.test/approve"}]}

    def get_subscription(self, subscription_id: str):
        return {"plan_id": self.plans[0]["id"], "status": "ACTIVE", "subscriber": {}}


def test_ensure_crew_catalog_creates_fr_and_en():
    spy = CatalogSpy()
    spy.products = []
    spy.plans = []

    async def run():
        out = await ensure_crew_supporter_catalog(spy)
        assert out.get("plan_id_fr")
        assert out.get("plan_id_en")
        assert len(spy.products) == 2
        assert len(spy.plans) == 2

    asyncio.run(run())


def test_create_crew_subscription_passes_locale_and_lang_hash():
    spy = CatalogSpy()

    async def run():
        await ensure_crew_supporter_catalog(spy)
        first = await create_crew_subscription(
            spy,
            return_url="https://a.test/r",
            cancel_url="https://a.test/c",
            client_key="buyer-1",
            lang="en",
        )
        second = await create_crew_subscription(
            spy,
            return_url="https://a.test/r",
            cancel_url="https://a.test/c",
            client_key="buyer-1",
            lang="fr",
        )
        assert first["lang"] == "en"
        assert second["lang"] == "fr"
        assert len(spy.subscriptions) == 2
        assert spy.subscriptions[0]["locale"] == "en-US"
        assert spy.subscriptions[1]["locale"] == "fr-FR"

    asyncio.run(run())


def test_approve_crew_subscription_accepts_either_plan_id():
    spy = CatalogSpy()

    async def run():
        catalog = await ensure_crew_supporter_catalog(spy)
        fr_plan = catalog["plan_id_fr"]
        en_plan = catalog["plan_id_en"]
        spy.get_subscription = lambda sid: {"plan_id": fr_plan, "status": "ACTIVE", "subscriber": {}}
        await approve_crew_subscription(spy, subscription_id="I-FR", plan_id=fr_plan)
        spy.get_subscription = lambda sid: {"plan_id": en_plan, "status": "ACTIVE", "subscriber": {}}
        await approve_crew_subscription(spy, subscription_id="I-EN", plan_id=en_plan)

    asyncio.run(run())


def test_invoice_remind_localized():
    class InvSpy:
        last = None

        def remind_invoice(self, invoice_id, *, subject, note):
            self.last = {"subject": subject, "note": note}
            return {"ok": True}

    spy = InvSpy()

    async def run():
        await remind_invoice(spy, "INV-1", lang="fr")
        assert "Rappel" in spy.last["subject"]
        await remind_invoice(spy, "INV-1", lang="en")
        assert "Reminder" in spy.last["subject"]

    asyncio.run(run())


def test_payout_default_note_localized():
    class PaySpy:
        last = None

        def create_payout(self, **kwargs):
            self.last = kwargs
            return {"batch_header": {"payout_batch_id": "B1"}}

    async def run():
        spy = PaySpy()
        ledger = get_ledger()
        await ledger.save_pledge({
            "_id": "p1",
            "kind": "project_pledge",
            "target_id": "proj-x",
            "status": "captured",
            "amount_eur": "20.00",
            "capture_id": "C1",
            "history": [],
        })
        proposal = await propose_project_payout(
            "proj-x",
            amount_eur="5.00",
            receiver_email="a@example.com",
        )
        await approve_project_payout(proposal["_id"], spy, lang="fr")
        assert "Versement" in spy.last["note"]
        proposal2 = await propose_project_payout(
            "proj-x",
            amount_eur="3.00",
            receiver_email="b@example.com",
        )
        await approve_project_payout(proposal2["_id"], spy, lang="en")
        assert "Berry-Mappemonde Escales payout" in spy.last["note"]

    asyncio.run(run())


def test_n35_miles_cart_no_project_fund_prose_and_single_capture_rule():
    async def run():
        body = await captain.chat("250 mi près de Dakar", treasurer=False, lang="fr")
        reply = str(body.get("reply") or "")
        lowered = reply.casefold()
        assert "la caisse est le financement projet" not in lowered
        assert reply.casefold().count(CAPTURE_RULES_FR.casefold()) == 1

    asyncio.run(run())


def test_llm_call_sites_pass_lang():
    app_dir = Path(__file__).resolve().parent.parent / "app"
    offenders: list[str] = []
    for path in app_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in {"ask_text", "ask_json"}:
                if not any(kw.arg == "lang" for kw in node.keywords):
                    offenders.append(f"{path.relative_to(app_dir.parent)}:{node.lineno}")
    assert offenders == []
