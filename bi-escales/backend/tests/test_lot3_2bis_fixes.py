"""Lot 3 audit 2bis (F2, F4, F5, F7, N36) unit tests."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import llm
from app.escales.captain import (
    _compose_chat_reply,
    _fund_place_label,
    _paypal_readonly_reply,
    chat,
    review,
)
from app.escales.milestones import record_evidence
from app.escales.pledges import authorize_pledge, capture_pledge, create_pledge, reset_ledger
from app.escales.toolkit_tools import ReadOnlyTools
from app.routers.escales import router, set_paypal_client_factory
from tests.schedule_clocks import near_mayotte_clock
from tests.test_escales_captain import Spy
from tests.test_escales_router import ADMIN, FakePayPal, _ready


class _PayPalSpy:
    def get_order(self, oid):
        return {"id": oid}

    def get_authorization(self, aid):
        return {"id": aid}

    def list_disputes(self, **kwargs):
        return {"items": [{"id": "D1"}]}

    def search_transactions(self, **kwargs):
        return {"transaction_details": [{"id": "T1"}, {"id": "T2"}]}

    def list_invoices(self, **kwargs):
        return {"items": []}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin-key")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", near_mayotte_clock())
    reset_ledger()
    monkeypatch.setattr(llm, "has_llm", lambda settings=None: False)
    yield
    reset_ledger()
    set_paypal_client_factory(None)


@pytest.fixture
def api(monkeypatch):
    reset_ledger()
    fake = FakePayPal()
    set_paypal_client_factory(lambda: fake)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client, fake
    set_paypal_client_factory(None)
    reset_ledger()


def test_f2_fr_transactions_et_litiges_return_both_tool_lines():
    reader = ReadOnlyTools(_PayPalSpy())
    reply = _paypal_readonly_reply(
        "Liste les transactions et litiges PayPal pour le trésorier",
        "fr",
        reader,
    )
    assert reply is not None
    lines = reply.split("\n")
    assert len(lines) == 2
    assert "Litiges PayPal" in lines[0]
    assert "Transactions PayPal" in lines[1]
    assert "lecture seule" in reply


def test_f2_en_transactions_and_disputes_return_both_tool_lines():
    reader = ReadOnlyTools(_PayPalSpy())
    reply = _paypal_readonly_reply(
        "Show PayPal transactions and disputes for the treasurer",
        "en",
        reader,
    )
    assert reply is not None
    lines = reply.split("\n")
    assert len(lines) == 2
    assert "PayPal disputes" in lines[0]
    assert "PayPal transactions" in lines[1]
    assert "(read-only)" in reply


def test_f4_chat_prompt_includes_fund_label_and_strips_wrong_common_fund(monkeypatch):
    import app.core.llm as llm_mod

    seen: dict = {}

    async def fake_ask_text(prompt, system=None, **kwargs):
        seen["prompt"] = prompt
        seen["system"] = system
        return (
            "This goes to the common fund for the stop. "
            "Thank you for supporting the leg."
        )

    monkeypatch.setattr(llm_mod, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm_mod, "ask_text", fake_ask_text)

    async def body():
        result = await chat("Je parraine 10 milles près de Brest", lang="fr")
        payload = json.loads(seen["prompt"])
        mid = str(payload["suggested"]["milestone_id"])
        assert payload.get("fund_label") == _fund_place_label(mid, "fr")
        assert "Name the fund exactly" in seen["system"] or "fund_label" in seen["system"]
        assert "fonds commun" not in result["reply"].casefold()
        assert "common fund" not in result["reply"].casefold()
        assert "Brest" in result["reply"]

    asyncio.run(body())


def test_f5_en_capture_rule_appears_once_when_model_repeats_it():
    suggested = {
        "amount_eur": "250.00",
        "currency": "EUR",
        "description": "250 sponsored miles",
        "milestone_id": "dep-dakar",
        "kind": "mile",
        "intent": "AUTHORIZE",
    }
    duplicate = (
        "Stop-level pledges (miles, nights, meals, care, berths) are captured "
        "on the boat's arrival at the stop and voided if the stop is cancelled. "
    )
    model = f"{duplicate}{duplicate}Thanks for your support."
    reply = _compose_chat_reply(
        model,
        suggested,
        "en",
        treasurer=False,
        ask_escale=False,
    )
    assert reply.casefold().count("voided if the stop is cancelled") == 1
    assert reply.casefold().count(duplicate.strip().casefold()) == 1


def test_f7_french_review_decision_uses_localized_verb(monkeypatch):
    import app.core.llm as llm_mod

    async def fake_ask_text(*_args, **_kwargs):
        return "Milestone Dakar: evidence covers 80 nautical miles toward Dakar."

    async def fake_ask_json(*_args, **_kwargs):
        return llm_mod.LlmJson({"proposal": "wait", "reason": "open"}, "nim", "m", "{}")

    monkeypatch.setattr(llm_mod, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm_mod, "ask_text", fake_ask_text)
    monkeypatch.setattr(llm_mod, "ask_json", fake_ask_json)

    async def body():
        await record_evidence("dakar", met=None, facts={"distance_nm": 80})
        result = await review("dakar", reader=None, lang="fr")
        assert "Décision : attendre." in result["justification"]
        assert "Decision:" not in result["justification"]
        assert " wait." not in result["justification"]

    asyncio.run(body())


def test_n36_public_common_fund_route(api):
    client, _fake = api
    empty = client.get("/api/escales/common-fund/fund")
    assert empty.status_code == 200
    assert empty.json()["milestone_id"] == "fonds-commun"
    assert empty.json()["income_eur"] == "0.00"
    _created, boat = _ready(client, "n36-fund", {
        "amount_eur": "12.00",
        "description": "fonds commun",
        "milestone_id": "",
        "kind": "common_fund",
    })
    assert client.post(
        f"/api/escales/pledges/{boat['id']}/capture", headers=ADMIN
    ).status_code == 200
    public = client.get("/api/escales/common-fund/fund").json()
    assert public["income_eur"] == "12.00"
    assert public["balance_eur"] == "12.00"
    assert "pledge_id" not in json.dumps(public)


async def _captured_common_fund(spy, amount, key):
    pledge = await create_pledge(
        amount_eur=amount,
        description="fonds commun",
        milestone_id="",
        kind="common_fund",
        client=spy,
        client_key=key,
    )
    await authorize_pledge(pledge["_id"], spy)
    await capture_pledge(pledge["_id"], spy)
    return pledge


def test_n36_captain_common_fund_public_without_treasurer():
    async def body():
        spy = Spy()
        await _captured_common_fund(spy, "12.00", "n36-chat")
        result = await chat("What is the common fund balance?", lang="en")
        assert result["fund"]["balance_eur"] == "12.00"
        assert "12.00" in result["reply"]
        assert "Only the treasurer can see the project fund totals." not in result["reply"]

    asyncio.run(body())
