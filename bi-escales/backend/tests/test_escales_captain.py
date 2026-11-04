"""Captain review, chat, number filter, and the read-only toolkit. No network."""
from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales import captain
from app.escales.captain import chat, review
from app.escales.milestones import filter_numbers, record_evidence
from app.escales.pledges import authorize_pledge, create_pledge, require_pledge, reset_ledger
from tests.near_horizon import seed_near
from app.escales.toolkit_tools import (
    ALLOWED_TOOLS,
    TOOLKIT_ORDER_ACTIONS,
    ReadOnlyTools,
    ToolNotAllowed,
    enabled_toolkit_methods,
    exposed_tools,
    toolkit_installed,
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.delenv("HELLOASSO_MEMBERSHIP_URL", raising=False)
    monkeypatch.delenv("ESCALES_TOOLKIT_ENABLED", raising=False)
    reset_ledger()
    asyncio.run(seed_near())
    import app.core.llm as llm
    monkeypatch.setattr(llm, "has_llm", lambda settings=None: False)
    yield
    reset_ledger()


class Spy:
    def __init__(self):
        self.calls = []
        self.n = 0

    def create_authorize_order(self, amount_eur, description, reference_id, idempotency_key=None):
        self.calls.append(("create", idempotency_key))
        self.n += 1
        order_id = f"ORDER{self.n}"
        return {
            "id": order_id,
            "links": [{"rel": "approve", "href": f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}"}],
        }

    def authorize_order(self, order_id):
        self.calls.append(("authorize", order_id))
        return {
            "id": order_id,
            "purchase_units": [{
                "payments": {"authorizations": [{"id": f"AUTH-{order_id}", "expiration_time": "2026-12-01T00:00:00Z"}]},
            }],
        }

    def capture_authorization(self, authorization_id, final=True):
        self.calls.append(("capture", authorization_id))
        return {"status": "COMPLETED"}

    def void_authorization(self, authorization_id):
        self.calls.append(("void", authorization_id))
        return {}

    def get_order(self, order_id):
        self.calls.append(("orders.get", order_id))
        return {"id": order_id, "status": "APPROVED"}

    def get_authorization(self, authorization_id):
        self.calls.append(("authorizations.get", authorization_id))
        return {"id": authorization_id, "status": "CREATED"}


def test_filter_numbers_drops_figures_absent_from_evidence():
    out = filter_numbers("Boat left La Rochelle with 12 pledges and 999 fans", {"pledges": 12})
    assert "12" in out
    assert "999" not in out
    assert "[?]" in out


def test_filter_numbers_accepts_equivalent_amount_spellings():
    facts = {"amount_eur": "120.00"}
    out = filter_numbers("Montants 120, 120.00 et 120,00.", facts)
    assert "[?]" not in out
    assert "120" in out
    assert "120.00" in out
    assert "120,00" in out
    assert filter_numbers("12", facts) == "[?]"
    assert filter_numbers("999", {"distance_nm": 120}) == "[?]"


def test_captain_source_has_no_capture_or_void():
    source = inspect.getsource(captain)
    assert "capture_authorization" not in source
    assert "void_authorization" not in source
    assert "paypal_client" not in source


def test_toolkit_exposes_only_readonly_gets():
    assert exposed_tools() == ALLOWED_TOOLS == ("orders.get", "authorizations.get")
    assert TOOLKIT_ORDER_ACTIONS == {"orders": {"get": True}}
    assert "capture" not in TOOLKIT_ORDER_ACTIONS["orders"]
    methods = enabled_toolkit_methods()
    if toolkit_installed():
        assert methods == ["get_order_details"]
    else:
        assert methods == []
    assert not any("capture" in name or "void" in name for name in methods)
    spy = Spy()
    reader = ReadOnlyTools(spy)
    assert reader.allowed() == ("orders.get", "authorizations.get")
    assert not hasattr(reader, "capture_authorization")
    assert not hasattr(reader, "void_authorization")
    assert reader.get("orders.get", "ORDER1")["status"] == "APPROVED"
    assert reader.get("authorizations.get", "AUTH1")["id"] == "AUTH1"
    with pytest.raises(ToolNotAllowed):
        reader.get("orders.capture", "ORDER1")
    with pytest.raises(ToolNotAllowed):
        reader.get("authorizations.void", "AUTH1")
    assert [call[0] for call in spy.calls] == ["orders.get", "authorizations.get"]


def test_captain_review_never_captures_or_voids():
    async def body():
        spy = Spy()
        pledge = await create_pledge(
            amount_eur="20.00",
            description="20 milles",
            milestone_id="dep-mayotte",
            client=spy,
            client_key="cap-1",
        )
        await authorize_pledge(pledge["_id"], spy)
        await record_evidence("dep-mayotte", met=True, facts={"port": "Mayotte"})
        result = await review("dep-mayotte", reader=ReadOnlyTools(spy))
        assert result["proposal"] == "capture"
        assert result["pledge_ids"] == [pledge["_id"]]
        assert "simulation" in (result["report"] + result["justification"])
        assert result["model_source"] == {"provider": "rules", "model": ""}
        names = [call[0] for call in spy.calls]
        assert "capture" not in names
        assert "void" not in names
        assert "orders.get" in names
        assert "authorizations.get" in names
        stored = await require_pledge(pledge["_id"])
        assert stored["status"] == "authorized"

        await record_evidence("dep-fort-de-france", met=False, facts={"port": "Fort-de-France"})
        other = await create_pledge(
            amount_eur="60.00",
            description="diner",
            milestone_id="dep-fort-de-france",
            client=spy,
            client_key="cap-2",
        )
        await authorize_pledge(other["_id"], spy)
        cancelled = await review("dep-fort-de-france", reader=ReadOnlyTools(spy))
        assert cancelled["proposal"] == "void"
        assert "void" not in [call[0] for call in spy.calls]
        assert "capture" not in [call[0] for call in spy.calls]
        assert (await require_pledge(other["_id"]))["status"] == "authorized"

    asyncio.run(body())


def test_review_strips_numbers_not_in_the_evidence(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return "12 boats confirmed and 999 spectators"

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        await record_evidence("dep-mayotte", met=True, facts={"boats": 12})
        result = await review("dep-mayotte", reader=None)
        text = result["justification"]
        assert "12" in text
        assert "999" not in text
        assert "[?]" in text
        assert result["proposal"] == "capture"
        assert result["model_source"] == {"provider": "llm", "model": ""}

    asyncio.run(body())


def test_chat_offers_membership_url_and_does_not_order(monkeypatch):
    monkeypatch.setenv(
        "HELLOASSO_MEMBERSHIP_URL",
        "https://www.helloasso.com/associations/blue-intelligence/adhesions/membre",
    )

    async def body():
        result = await chat("Je veux adhérer et parrainer 20 milles près de Mayotte")
        assert result["membership_url"].startswith("https://www.helloasso.com/")
        assert result["membership_url"] in result["reply"]
        pledge = result["suggested_pledge"]
        assert pledge["amount_eur"] == "20.00"
        assert pledge["currency"] == "EUR"
        assert pledge["intent"] == "AUTHORIZE"
        assert pledge["milestone_id"] == "mayotte"
        assert "order_id" not in result
        assert "999" not in result["reply"]
        assert result["model_source"] == {"provider": "rules", "model": ""}

    asyncio.run(body())


def test_chat_strips_an_invented_price(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return "Le prix inventé est 999 EUR."

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setenv("HELLOASSO_MEMBERSHIP_URL", "https://www.helloasso.com/associations/blue-intelligence/adhesions/membre")

    async def body():
        result = await chat("Parraine 20 milles près de Mayotte")
        assert "999" not in result["reply"]
        assert "[?]" in result["reply"]
        assert result["membership_url"] in result["reply"]
        assert result["suggested_pledge"]["amount_eur"] == "20.00"
        assert result["model_source"] == {"provider": "llm", "model": ""}

    asyncio.run(body())


def test_chat_repeats_the_pledge_in_the_message_language(monkeypatch):
    import app.core.llm as llm

    seen = {}

    async def fake_ask_text(prompt, system=None, **_kwargs):
        seen["system"] = system
        return "Of course, that leg can be sponsored."

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setenv(
        "HELLOASSO_MEMBERSHIP_URL",
        "https://www.helloasso.com/associations/blue-intelligence/adhesions/membre",
    )

    async def body():
        result = await chat("I'd like to sponsor 120 nautical miles near Lorient")
        assert "Reply in English" in seen["system"]
        assert "French" not in seen["system"]
        reply = result["reply"]
        assert "120.00" in reply
        assert "120 milles parrainés" in reply
        assert "lorient" in reply
        assert "AUTHORIZE" in reply
        assert result["membership_url"] in reply
        assert reply.count("— The captain") == 1
        assert "— Le capitaine" not in reply
        assert len(reply.split()) <= 80
        assert "[?]" not in reply

    asyncio.run(body())


def test_treasurer_questions_skip_the_model(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        raise AssertionError("the model must not answer a treasurer question")

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        result = await chat(
            "Mon autorisation date d'il y a 28 jours, est-ce que vous allez l'encaisser ou l'annuler ?"
        )
        reply = result["reply"].lower()
        assert "trésorier" in reply
        assert "29" not in result["reply"]
        assert "capture" not in reply
        assert "void" not in reply
        assert result["reply"].count("— Le capitaine") == 1
        assert result["model_source"] == {"provider": "rules", "model": ""}
        assert len(result["reply"].split()) <= 80

    asyncio.run(body())


def test_chat_keeps_one_signature_and_at_most_80_words(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return ("mot " * 200) + "— Le capitaine — Le capitaine"

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        result = await chat("Je parraine 10 milles près de Brest")
        reply = result["reply"]
        assert reply.count("— Le capitaine") == 1
        assert len(reply.split()) <= 80
        assert "10.00" in reply
        assert "brest" in reply

    asyncio.run(body())
