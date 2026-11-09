"""Mile sponsorship certificates: issue-on-success, opaque URLs, PNG/PDF."""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import llm
from app.escales.certificates import (
    _CAPTAIN_FALLBACK,
    load_certificate,
    payer_proof_expected,
    reset_certificate_store,
)
from app.escales.pledges import require_pledge, reset_ledger
from app.routers.escales import router, set_paypal_client_factory

MILE_PLEDGE = {
    "amount_eur": "3.00",
    "description": "3 miles La Rochelle",
    "milestone_id": "dep-la-rochelle",
    "kind": "mile",
    "contributor": "Pat Dupont",
}


class FakePayPal:
    def __init__(self):
        self.n = 0

    def create_authorize_order(self, amount_eur, description, reference_id, idempotency_key=None):
        self.n += 1
        order_id = f"ORDER{self.n}"
        return {
            "id": order_id,
            "status": "CREATED",
            "intent": "AUTHORIZE",
            "links": [{"rel": "approve", "href": f"https://sandbox.paypal.com/checkoutnow?token={order_id}"}],
        }

    def authorize_order(self, order_id, **kwargs):
        return {
            "id": order_id,
            "purchase_units": [{
                "payments": {"authorizations": [{"id": f"AUTH-{order_id}", "expiration_time": "2099-01-01T00:00:00Z"}]},
            }],
        }


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.delenv("ESCALES_LLM_ENABLED", raising=False)
    monkeypatch.delenv("ESCALES_ENV", raising=False)
    reset_ledger()
    reset_certificate_store()
    llm.reset_llm_budget()
    fake = FakePayPal()
    set_paypal_client_factory(lambda: fake)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client
    set_paypal_client_factory(None)
    reset_ledger()
    reset_certificate_store()


def _ready_mile(client):
    created = client.post("/api/escales/pledges", json=MILE_PLEDGE, headers={"PayPal-Request-Id": "cert-1"})
    assert created.status_code == 200, created.text
    pledge_id = created.json()["id"]
    authorized = client.post(f"/api/escales/pledges/{pledge_id}/authorize")
    assert authorized.status_code == 200
    return pledge_id, authorized.json()


def _issue(client, pledge_id, *, lang="en", **fields):
    proof = payer_proof_expected(asyncio.run(require_pledge(pledge_id)))
    payload = {"payer_proof": proof, **fields}
    return client.post(f"/api/escales/pledges/{pledge_id}/certificate?lang={lang}", json=payload)


def test_issue_certificate_on_success(api):
    client = api
    pledge_id, _ = _ready_mile(client)
    issued = _issue(client, pledge_id, lang="en")
    assert issued.status_code == 200
    body = issued.json()
    assert body["token"]
    assert "/api/escales/certificates/" in body["png"]
    assert body["png"].endswith(".png")
    assert body["pdf"].endswith(".pdf")
    assert "Pat" not in body["png"]
    assert pledge_id not in body["png"]


def test_certificate_requires_payer_proof(api):
    client = api
    pledge_id, _ = _ready_mile(client)
    missing = client.post(f"/api/escales/pledges/{pledge_id}/certificate?lang=en", json={})
    assert missing.status_code == 403
    wrong = client.post(
        f"/api/escales/pledges/{pledge_id}/certificate?lang=en",
        json={"payer_proof": "not-the-order"},
    )
    assert wrong.status_code == 403


def test_idempotent_issue_keeps_first_display_name(api):
    client = api
    pledge_id, _ = _ready_mile(client)
    proof = payer_proof_expected(asyncio.run(require_pledge(pledge_id)))
    first = client.post(
        f"/api/escales/pledges/{pledge_id}/certificate?lang=en",
        json={"payer_proof": proof, "display_name": "First Name"},
    )
    second = client.post(
        f"/api/escales/pledges/{pledge_id}/certificate?lang=en",
        json={"payer_proof": proof, "display_name": "Second Name"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["token"] == second.json()["token"]
    doc = asyncio.run(load_certificate(first.json()["token"]))
    assert doc["display_name"] == "First Name"


def test_unknown_token_is_404(api):
    client = api
    assert client.get("/api/escales/certificates/does-not-exist.png").status_code == 404
    assert client.get("/api/escales/certificates/does-not-exist.pdf").status_code == 404


def test_png_pdf_valid_fr_and_en(api):
    client = api
    pledge_id, _ = _ready_mile(client)
    token = _issue(client, pledge_id, lang="fr").json()["token"]
    for lang in ("fr", "en"):
        for ext, magic in (("png", b"\x89PNG"), ("pdf", b"%PDF")):
            path = f"/api/escales/certificates/{token}.{ext}?lang={lang}"
            response = client.get(path)
            assert response.status_code == 200
            data = response.content
            assert len(data) > 0
            assert data.startswith(magic)


def test_logs_never_include_pii_or_full_token(api, caplog):
    client = api
    pledge_id, _ = _ready_mile(client)
    with caplog.at_level(logging.INFO):
        body = _issue(
            client,
            pledge_id,
            lang="en",
            display_name="Secret Sailor",
        ).json()
        token = body["token"]
        client.get(f"/api/escales/certificates/{token}.png")
        client.get(f"/api/escales/certificates/{token}.pdf")
    blob = "\n".join(r.message for r in caplog.records if r.name == "escales.certificates")
    assert "Secret" not in blob
    assert "Sailor" not in blob
    assert pledge_id not in blob
    assert "Pat" not in blob
    assert token not in blob


def test_llm_failure_uses_fallback(api, monkeypatch):
    monkeypatch.setenv("ESCALES_LLM_ENABLED", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    calls = {"n": 0}

    async def boom(*_a, **_k):
        calls["n"] += 1
        raise RuntimeError("provider down")

    monkeypatch.setattr(llm, "ask_text", boom)
    monkeypatch.setattr(llm, "has_llm", lambda: True)
    client = api
    pledge_id, _ = _ready_mile(client)
    issued = _issue(client, pledge_id, lang="en")
    assert issued.status_code == 200
    assert calls["n"] == 1
    token = issued.json()["token"]
    doc = asyncio.run(load_certificate(token))
    assert doc
    assert doc["captain_text"] == _CAPTAIN_FALLBACK["en"]


def test_idempotent_download_and_single_llm_call(api, monkeypatch):
    monkeypatch.setenv("ESCALES_LLM_ENABLED", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    calls = {"n": 0}

    async def once(*_a, **_k):
        calls["n"] += 1

        class Result:
            text = "Steady winds and fair seas for this sponsored mile."

        return Result()

    monkeypatch.setattr(llm, "ask_text", once)
    monkeypatch.setattr(llm, "has_llm", lambda: True)
    client = api
    pledge_id, _ = _ready_mile(client)
    first = _issue(client, pledge_id, lang="en")
    second = _issue(client, pledge_id, lang="en")
    assert first.json()["token"] == second.json()["token"]
    assert calls["n"] == 1
    token = first.json()["token"]
    png_a = client.get(f"/api/escales/certificates/{token}.png?lang=en").content
    png_b = client.get(f"/api/escales/certificates/{token}.png?lang=en").content
    assert png_a == png_b
    doc = asyncio.run(load_certificate(token))
    assert "Steady winds" in str(doc.get("captain_text") or "")


def test_async_consume_llm_call_is_awaited_once(api, monkeypatch):
    monkeypatch.setenv("ESCALES_LLM_ENABLED", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    budget_calls = {"n": 0}

    async def async_consume():
        budget_calls["n"] += 1
        return True

    async def once(*_a, **_k):
        class Result:
            text = "Fair breeze for this mile."

        return Result()

    monkeypatch.setattr(llm, "consume_llm_call", async_consume)
    monkeypatch.setattr(llm, "ask_text", once)
    monkeypatch.setattr(llm, "has_llm", lambda: True)
    client = api
    pledge_id, _ = _ready_mile(client)
    issued = _issue(client, pledge_id, lang="en")
    assert issued.status_code == 200
    assert budget_calls["n"] == 1


def test_refused_llm_cap_uses_fallback(api, monkeypatch):
    monkeypatch.setenv("ESCALES_LLM_ENABLED", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    async def deny():
        return False

    async def must_not_run(*_a, **_k):
        raise AssertionError("ask_text must not run when the daily cap is full")

    monkeypatch.setattr(llm, "consume_llm_call", deny)
    monkeypatch.setattr(llm, "ask_text", must_not_run)
    monkeypatch.setattr(llm, "has_llm", lambda: True)
    client = api
    pledge_id, _ = _ready_mile(client)
    token = _issue(client, pledge_id, lang="en").json()["token"]
    doc = asyncio.run(load_certificate(token))
    assert doc["captain_text"] == _CAPTAIN_FALLBACK["en"]


def test_created_mile_pledge_cannot_issue(api):
    client = api
    created = client.post("/api/escales/pledges", json=MILE_PLEDGE, headers={"PayPal-Request-Id": "cert-2"})
    pledge_id = created.json()["id"]
    proof = created.json().get("order_id")
    denied = client.post(
        f"/api/escales/pledges/{pledge_id}/certificate",
        json={"payer_proof": proof},
    )
    assert denied.status_code in {400, 422}
