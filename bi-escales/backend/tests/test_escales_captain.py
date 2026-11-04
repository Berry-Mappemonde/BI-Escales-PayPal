"""Captain review, chat, number filter, and the read-only toolkit. No network."""
from __future__ import annotations

import asyncio
import inspect
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales import captain
from app.escales.captain import chat, review
from app.escales.milestones import filter_numbers, record_evidence
from app.escales.pledges import authorize_pledge, capture_pledge, create_pledge, get_ledger, require_pledge, reset_ledger
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
    french = filter_numbers("Montants 120, 120.00 et 120,00.", facts, lang="fr")
    assert "[?]" not in french
    assert french.startswith("Montants 120, ")
    assert "120,00 €" in french
    assert "120.00" not in french
    english = filter_numbers("Amounts 120, 120.00 and 120,00 EUR.", facts, lang="en")
    assert "[?]" not in english
    assert "120.00 EUR" in english
    assert "120,00" not in english
    assert "€" not in english
    assert filter_numbers("12", facts, lang="en") == "[?]"
    assert filter_numbers("999", {"distance_nm": 120}, lang="fr") == "[?]"


def test_filter_numbers_keeps_a_french_comma_and_a_derived_difference():
    facts = {"amount_eur": "1.00"}
    assert filter_numbers("Le mille coûte 1,00 €.", facts, lang="fr") == "Le mille coûte 1,00 €."
    assert filter_numbers("Le mille coûte 1.00 EUR.", facts, lang="fr") == "Le mille coûte 1,00 €."
    assert filter_numbers("The mile costs 1,00 €.", facts, lang="en") == "The mile costs 1.00 EUR."
    assert filter_numbers("The mile costs 1.00 EUR.", facts, lang="en") == "The mile costs 1.00 EUR."
    derived = filter_numbers(
        "La jambe tombe 170 milles en dessous des 250 prévus après 80.",
        {"planned_nm": 250, "sailed_nm": 80},
        lang="fr",
    )
    assert "170" in derived
    assert "250" in derived
    assert "80" in derived
    assert "[?]" not in derived
    assert filter_numbers("999", {"planned_nm": 250, "sailed_nm": 80}) == "[?]"


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
        result = await review("dep-mayotte", reader=None, lang="en")
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
        assert pledge["milestone_id"] == "dep-dzaoudzi-mayotte"
        assert pledge["kind"] == "mile"
        assert pledge["simulated"] is True
        assert pledge["price_label"] == "simulated price"
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

    async def fake_ask_text(prompt, system=None, **kwargs):
        seen["system"] = system
        seen["temperature"] = kwargs.get("temperature")
        return "Of course, that leg can be sponsored."

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setenv(
        "HELLOASSO_MEMBERSHIP_URL",
        "https://www.helloasso.com/associations/blue-intelligence/adhesions/membre",
    )

    async def body():
        result = await chat("I'd like to sponsor 120 nautical miles near Lorient")
        assert seen["temperature"] == 0.3
        assert "Reply in English" in seen["system"]
        assert "French" not in seen["system"]
        reply = result["reply"]
        assert "120.00 EUR" in reply
        assert "120,00" not in reply
        assert "€" not in reply
        assert "120 sponsored miles" in reply
        assert "milles parrainés" not in reply
        assert "Lorient" in reply
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
        assert result["suggested_pledge"] is None
        assert "mille" not in result["reply"].lower()
        assert "unspecified" not in result["reply"]
        english = await chat("My authorization is 28 days old. Will you capture or void it?")
        assert "treasurer review" in english["reply"]
        assert "trésorier" not in english["reply"]
        assert "Le capitaine" not in english["reply"]
        assert english["reply"].count("— The captain") == 1
        assert english["model_source"] == {"provider": "rules", "model": ""}
        assert english["suggested_pledge"] is None
        assert "sponsored" not in english["reply"].lower()

    asyncio.run(body())


def test_a_complete_model_answer_is_not_followed_by_the_french_template(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return (
            "Oui, c'est possible. Voici le montant calculé : 120,00 EUR, "
            "description : 120 milles parrainés, étape : Lorient, intention : AUTHORIZE."
        )

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        result = await chat("Je voudrais parrainer 120 milles près de Lorient")
        assert result["reply"].count("Promesse calculée") == 1
        assert "120,00 €" in result["reply"]
        assert "120.00" not in result["reply"]
        assert result["reply"].count("— Le capitaine") == 1

    asyncio.run(body())


def test_a_model_proposal_does_not_replace_the_code_decision(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return '{"proposal":"reauthorize","reason":"the model prefers to wait"}'

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        await record_evidence("dep-mayotte", met=True, facts={"port": "Mayotte"})
        result = await review("dep-mayotte", reader=None)
        assert result["proposal"] == "capture"
        assert result["proposal"] != "reauthorize"

    asyncio.run(body())


def test_rules_amounts_follow_the_reply_language():
    async def body():
        french = await chat("Je parraine 20 milles près de Mayotte")
        assert "20,00 €" in french["reply"]
        assert "20.00" not in french["reply"]
        assert "Promesse calculée" in french["reply"]
        assert "milles parrainés" in french["reply"]
        assert "sponsored" not in french["reply"]
        assert french["suggested_pledge"]["amount_eur"] == "20.00"
        english = await chat("I'd like to sponsor 20 nautical miles near Lorient")
        assert "20.00 EUR" in english["reply"]
        assert "20,00" not in english["reply"]
        assert "€" not in english["reply"]
        assert "20 sponsored miles" in english["reply"]
        assert "milles" not in english["reply"]
        assert "Computed pledge" in english["reply"]
        assert english["model_source"] == {"provider": "rules", "model": ""}

    asyncio.run(body())


def test_number_guard_rewrites_amounts_into_the_reply_language(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(prompt, system=None, **_kwargs):
        if system and "English" in system:
            return "120 sponsored miles, lorient, 120,00 €, AUTHORIZE."
        return "120 milles parrainés, Lorient, 120.00 EUR, AUTHORIZE."

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        french = await chat("Je voudrais parrainer 120 milles près de Lorient")
        assert "120,00 €" in french["reply"]
        assert "120.00" not in french["reply"]
        assert "120 milles parrainés" in french["reply"]
        assert french["reply"].count("Promesse calculée") == 1
        english = await chat("I'd like to sponsor 120 nautical miles near Lorient")
        assert "120.00 EUR" in english["reply"]
        assert "120,00" not in english["reply"]
        assert "€" not in english["reply"]
        assert "120 sponsored miles" in english["reply"]
        assert "milles parrainés" not in english["reply"]
        assert english["reply"].count("Computed pledge") == 1

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
        assert "10,00 €" in reply
        assert "10.00" not in reply
        assert "Brest" in reply

    asyncio.run(body())


def test_suggest_pledge_adds_every_item_in_the_message():
    pledge = captain.suggest_pledge("250 mi + dinner 60 € près de Dakar")
    assert pledge["amount_eur"] == "310.00"
    assert pledge["currency"] == "EUR"
    assert pledge["milestone_id"] == "dep-dakar"
    assert pledge["intent"] == "AUTHORIZE"
    assert "milles parrainés" in pledge["description"]
    assert "dîner" in pledge["description"].lower()
    assert "sponsored" not in pledge["description"]
    english = captain.suggest_pledge("250 mi + dinner 60 € near Dakar", lang="en")
    assert english["amount_eur"] == "310.00"
    assert english["milestone_id"] == "dep-dakar"
    assert english["description"] == "250 sponsored miles and port dinner"
    assert "milles" not in english["description"]
    separate = captain.suggest_pledge("100 mi et 150 miles près de Dakar")
    assert separate["amount_eur"] == "250.00"


def test_chat_sums_miles_and_dinner_for_dakar():
    async def body():
        french = await chat("250 mi + dinner 60 € près de Dakar")
        assert french["suggested_pledge"]["amount_eur"] == "310.00"
        assert "310,00 €" in french["reply"]
        assert "250,00" not in french["reply"]
        assert "milles parrainés" in french["reply"]
        english = await chat("I'd like to sponsor 250 mi + dinner 60 € near Dakar")
        assert english["suggested_pledge"]["amount_eur"] == "310.00"
        assert "310.00 EUR" in english["reply"]
        assert "310,00" not in english["reply"]
        assert "sponsored miles" in english["reply"]
        assert "milles parrainés" not in english["reply"]

    asyncio.run(body())


def test_status_questions_have_no_pledge_suggestion(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        raise AssertionError("the model must not answer a status question")

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        french = await chat("Quel est le statut ?")
        assert french["suggested_pledge"] is None
        assert "mille" not in french["reply"].lower()
        assert "unspecified" not in french["reply"]
        assert "1,00" not in french["reply"]
        assert french["reply"].count("— Le capitaine") == 1
        assert french["model_source"] == {"provider": "rules", "model": ""}
        english = await chat("What is the status?")
        assert english["suggested_pledge"] is None
        assert "sponsored" not in english["reply"].lower()
        assert "milles" not in english["reply"]
        assert "1.00" not in english["reply"]
        assert "unspecified" not in english["reply"]
        assert english["reply"].count("— The captain") == 1

    asyncio.run(body())


def test_french_long_signature_is_kept_once(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return "Bien reçu. Capitaine Blue Intelligence Escales — Le capitaine"

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        result = await chat("Je parraine 10 milles près de Brest")
        reply = result["reply"]
        assert "Blue Intelligence" not in reply
        assert reply.lower().count("capitaine") == 1
        assert reply.count("— Le capitaine") == 1

    asyncio.run(body())


def test_english_long_signature_is_kept_once(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return "Noted. Captain Blue Intelligence Escales — The captain"

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        result = await chat("I'd like to sponsor 10 nautical miles near Brest")
        reply = result["reply"]
        assert "Blue Intelligence" not in reply
        assert reply.count("— The captain") == 1
        assert "Le capitaine" not in reply

    asyncio.run(body())


def test_english_report_templates_say_milestone_not_jalon():
    evidence = {"source": "simulation", "provider": "NAVIGUIDE", "flag": "simulation"}
    english = captain._fallback_report("lorient", "capture", evidence, lang="en")
    assert "Jalon" not in english
    assert "Milestone Lorient" in english
    french = captain._fallback_report("lorient", "wait", evidence, lang="fr")
    assert "Jalon Lorient" in french
    assert "Milestone" not in french
    shaped = captain._shape_report(
        "Jalon lorient is late. The treasurer alone decides.",
        "lorient",
        "en",
    )
    assert "Jalon" not in shaped
    assert "jalon" not in shaped.lower()
    assert "Milestone" in shaped
    assert "Jalon" not in captain._chat_system("en")
    assert "Jalon" not in captain._report_system("lorient")
    assert "Jalon" not in captain._fallback_report("brest", "wait", {}, lang="en")


def test_advisory_proposal_drops_a_false_expiry_under_29_days():
    dropped = captain.validate_advisory_proposal(
        "reauthorize",
        "the 28-day authorization has expired",
        age_days=28,
    )
    assert dropped["advisory"] is True
    assert dropped["label"] == "advisory"
    assert dropped["proposal"] is None
    assert dropped["raw_proposal"] == "reauthorize"
    assert "expired" not in (dropped["reason"] or "").lower()
    assert dropped["authorization_valid"] is True
    assert dropped["dropped"] is True
    voided = captain.validate_advisory_proposal(
        "void",
        "the 28-day authorization has expired",
        age_days=None,
    )
    assert voided["proposal"] is None
    assert voided["authorization_age_days"] == 28
    assert voided["authorization_valid"] is True
    assert "expired" not in (voided["reason"] or "").lower()
    kept = captain.validate_advisory_proposal(
        "void", "milestone not met", age_days=28, met=False,
    )
    assert kept["proposal"] == "void"
    assert kept["reason"] == "milestone not met"
    assert kept["dropped"] is False
    assert kept["contradicted"] is False
    assert kept["code_decision"] == "void"
    assert kept["advisory"] is True
    older = captain.validate_advisory_proposal(
        "void",
        "the 29-day authorization has expired",
        age_days=29,
        met=False,
    )
    assert older["proposal"] == "void"
    assert older["authorization_valid"] is False
    assert older["dropped"] is False
    assert older["advisory"] is True
    reauthorize = captain.validate_advisory_proposal(
        "reauthorize",
        "the 29-day authorization has expired",
        age_days=29,
        met=False,
    )
    assert reauthorize["proposal"] is None
    assert reauthorize["raw_proposal"] == "reauthorize"
    assert reauthorize["code_decision"] == "void"
    assert reauthorize["contradicted"] is True
    assert reauthorize["dropped"] is True


def test_review_labels_ask_json_as_advisory_and_drops_a_28_day_reauthorize(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return "Jalon dep-mayotte is ready. The treasurer decides."

    async def fake_ask_json(*_args, **_kwargs):
        return llm.LlmJson(
            {"proposal": "void", "reason": "the 28-day authorization has expired"},
            "nim",
            "test-model",
            '{"proposal":"void","reason":"the 28-day authorization has expired"}',
        )

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setattr(llm, "ask_json", fake_ask_json)

    async def body():
        spy = Spy()
        pledge = await create_pledge(
            amount_eur="20.00",
            description="20 milles",
            milestone_id="dep-mayotte",
            client=spy,
            client_key="age-28",
        )
        await authorize_pledge(pledge["_id"], spy)
        stored = await require_pledge(pledge["_id"])
        stored["authorization_age_days"] = 28
        await get_ledger().save_pledge(stored)
        await record_evidence("dep-mayotte", met=True, facts={"port": "Mayotte"})
        result = await review("dep-mayotte", reader=None, lang="en")
        assert result["proposal"] == "capture"
        advisory = result["llm_proposal"]
        assert advisory["advisory"] is True
        assert advisory["label"] == "advisory"
        assert advisory["proposal"] is None
        assert advisory["raw_proposal"] == "void"
        assert "expired" not in (advisory["reason"] or "").lower()
        assert advisory["authorization_age_days"] == 28
        assert advisory["authorization_valid"] is True
        assert "Jalon" not in result["report"]
        assert "Jalon" not in result["justification"]
        assert "Milestone" in result["report"]
        assert (await require_pledge(pledge["_id"]))["status"] == "authorized"

    asyncio.run(body())


def test_advisory_proposal_drops_a_decision_that_is_not_the_code_decision():
    capture = captain.validate_advisory_proposal("capture", "the leg looks ready")
    assert capture["dropped"] is True
    assert capture["contradicted"] is True
    assert capture["proposal"] is None
    assert capture["raw_proposal"] == "capture"
    assert capture["code_decision"] == "wait"
    unmet = captain.validate_advisory_proposal("capture", "not validated", met=False)
    assert unmet["dropped"] is True
    assert unmet["contradicted"] is True
    assert unmet["proposal"] is None
    assert unmet["code_decision"] == "void"
    matched = captain.validate_advisory_proposal("capture", "milestone met", met=True)
    assert matched["dropped"] is False
    assert matched["contradicted"] is False
    assert matched["proposal"] == "capture"
    assert matched["code_decision"] == "capture"


def test_advisory_proposal_drops_a_one_day_expiry_claim():
    english = captain.validate_advisory_proposal(
        "void",
        "Authorization expires in 1 day",
        age_days=10,
        met=False,
    )
    assert english["dropped"] is True
    assert english["contradicted"] is True
    assert english["authorization_valid"] is True
    assert english["proposal"] is None
    assert "expir" not in (english["reason"] or "").lower()
    assert "1 day" not in (english["reason"] or "")
    french = captain.validate_advisory_proposal(
        "reauthorize",
        "L'autorisation va expire dans un jour",
        age_days=4,
        met=True,
    )
    assert french["dropped"] is True
    assert french["contradicted"] is True
    assert french["proposal"] is None
    assert french["code_decision"] == "capture"
    assert french["authorization_valid"] is True
    assert "expir" not in (french["reason"] or "").lower()
    assert "jour" not in (french["reason"] or "").lower()


def test_model_signature_collapses_to_one_in_both_languages(monkeypatch):
    import app.core.llm as llm

    replies = [
        "Bien reçu. Capitaine de la Blue Intelligence Escales — Le capitaine",
        "Noted. Blue Intelligence Escales Captain — The captain",
    ]

    async def fake_ask_text(*_args, **_kwargs):
        return replies.pop(0)

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        french = await chat("Je parraine 10 milles près de Brest")
        french_reply = french["reply"]
        assert "Blue Intelligence" not in french_reply
        assert french_reply.lower().count("capitaine") == 1
        assert french_reply.count("— Le capitaine") == 1
        assert "The captain" not in french_reply
        english = await chat("I'd like to sponsor 10 nautical miles near Brest")
        english_reply = english["reply"]
        assert "Blue Intelligence" not in english_reply
        assert english_reply.lower().count("captain") == 1
        assert english_reply.count("— The captain") == 1
        assert "Le capitaine" not in english_reply

    asyncio.run(body())


def test_unset_membership_url_strips_invented_links(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return (
            "Promesse notée. Membership: "
            "https://www.helloasso.com/associations/berry-mappemonde/adhesions/adhesion-[?]-[?]."
        )

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.delenv("HELLOASSO_MEMBERSHIP_URL", raising=False)

    async def body():
        result = await chat("Je parraine 120 milles près de Lorient")
        reply = result["reply"]
        assert result["membership_url"] == ""
        assert "http" not in reply.lower()
        assert "helloasso" not in reply.lower()
        assert "adhesion" not in reply.lower()
        assert "membership" not in reply.lower()
        assert "adhésion" not in reply.lower()
        assert "configur" not in reply.lower()
        assert "[?]" not in reply
        assert "120,00 €" in reply
        assert reply.count("— Le capitaine") == 1

    asyncio.run(body())


def test_only_the_configured_membership_url_is_injected(monkeypatch):
    import app.core.llm as llm

    official = "https://www.helloasso.com/associations/blue-intelligence/adhesions/membre"

    async def fake_ask_text(*_args, **_kwargs):
        return "Membership: https://www.helloasso.com/associations/berry-mappemonde/adhesions/adhesion-2026."

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setenv("HELLOASSO_MEMBERSHIP_URL", official)

    async def body():
        result = await chat("I'd like to sponsor 120 nautical miles near Lorient")
        reply = result["reply"]
        assert reply.count(official) == 1
        assert "berry-mappemonde" not in reply
        assert "adhesion-2026" not in reply
        assert "[?]" not in reply
        assert "120.00 EUR" in reply

    asyncio.run(body())


def test_reached_leg_prompt_says_there_is_no_remaining_distance(monkeypatch):
    import app.core.llm as llm

    seen = {}

    async def fake_ask_text(prompt, system=None, **_kwargs):
        seen["system"] = system
        return "Lorient is 120 nautical miles away. The treasurer decides."

    async def fake_ask_json(*_args, **_kwargs):
        return llm.LlmJson(
            {"proposal": "capture", "reason": "looks reached"},
            "nim",
            "test-model",
            "{}",
        )

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setattr(llm, "ask_json", fake_ask_json)
    prompt = captain._report_system("lorient", True, "en")
    assert "Write in English only." in prompt
    assert "This leg was reached." not in prompt
    assert "no remaining distance" not in prompt.lower()
    assert "exactly 1 short complete sentence" in prompt
    waiting = captain._report_system("lorient", False, "en")
    assert "was reached" not in waiting
    assert "exactly 2 short complete sentences" in waiting
    assert "no remaining distance" not in waiting

    async def body():
        await record_evidence("lorient", met=True, facts={"distance_nm": 120})
        result = await review("lorient", reader=None, lang="en")
        assert "Write in English only." in seen["system"]
        assert "This leg was reached." not in seen["system"]
        assert "away" not in result["report"].lower()
        assert "away" not in result["justification"].lower()
        assert "Milestone Lorient was reached" in result["report"]
        assert "no remaining distance" in result["report"]
        assert result["proposal"] == "capture"
        advisory = result["llm_proposal"]
        assert advisory["proposal"] == "capture"
        assert advisory["code_decision"] == "capture"
        assert advisory["contradicted"] is False

    asyncio.run(body())


def test_reached_sentence_follows_the_report_language(monkeypatch):
    import app.core.llm as llm

    sparse_english = "Arrival recorded at Lorient. Simulation flag stands."
    assert captain.message_lang(sparse_english) == "fr"
    replies = [
        sparse_english,
        "L'arrivée est enregistrée à Lorient. La preuve est une simulation.",
    ]

    async def fake_ask_text(*_args, **_kwargs):
        return replies.pop(0)

    async def fake_ask_json(*_args, **_kwargs):
        return llm.LlmJson({"proposal": "capture", "reason": "met"}, "nim", "test-model", "{}")

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setattr(llm, "ask_json", fake_ask_json)

    async def body():
        await record_evidence("lorient", met=True, facts={"distance_nm": 120})
        english = await review("lorient", reader=None, lang="en")
        assert "Milestone Lorient was reached" in english["report"]
        assert "no remaining distance" in english["report"]
        assert "L'escale" not in english["report"]
        assert "atteinte" not in english["report"]
        assert "L'escale" not in english["justification"]
        await record_evidence("dakar", met=True, facts={"distance_nm": 80})
        french = await review("dakar", reader=None, lang="fr")
        assert "L'escale Dakar est atteinte" in french["report"]
        assert "sans distance restante" in french["report"]
        assert "was reached" not in french["report"]
        assert "no remaining distance" not in french["report"]
        assert "Milestone" not in french["report"]

    asyncio.run(body())


def test_chat_punctuation_is_one_stop_in_both_languages(monkeypatch):
    import app.core.llm as llm

    replies = [
        "Funds will be released.. — The captain. I am the.",
        "Les fonds sont libérés.. — Le capitaine. Je suis le.",
    ]

    async def fake_ask_text(*_args, **_kwargs):
        return replies.pop(0)

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        english = await chat("I'd like to sponsor 10 nautical miles near Brest")
        reply = english["reply"]
        assert ".." not in reply
        assert "I am the" not in reply
        assert "released." in reply
        assert reply.count("— The captain") == 1
        assert not reply.endswith("..")
        french = await chat("Je parraine 10 milles près de Brest")
        french_reply = french["reply"]
        assert ".." not in french_reply
        assert "Je suis le" not in french_reply
        assert "libérés." in french_reply
        assert french_reply.count("— Le capitaine") == 1

    asyncio.run(body())


def test_report_strips_echoed_instructions_in_both_languages(monkeypatch):
    import app.core.llm as llm

    seen = {}
    replies = [
        (
            "The decision field is fixed as capture. "
            "This advisory is not executed. "
            "Arrival recorded at Lorient. The boat is. "
            "Decision: capture. Decision: capture."
        ),
        (
            "Le champ de décision est fixé sur capture. "
            "Ceci est consultatif et n'est pas exécuté. "
            "L'arrivée est enregistrée à Lorient. Le bateau est. "
            "Décision : capture. Décision : capture."
        ),
    ]

    async def fake_ask_text(*_args, **kwargs):
        seen["max_tokens"] = kwargs.get("max_tokens")
        seen["system"] = kwargs.get("system")
        return replies.pop(0)

    async def fake_ask_json(*_args, **_kwargs):
        return llm.LlmJson({"proposal": "wait", "reason": "echo"}, "nim", "test-model", "{}")

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setattr(llm, "ask_json", fake_ask_json)
    prompt = captain._report_system("lorient", lang="en", reached=True)
    assert "Never stop mid-sentence." in prompt
    assert "decision field is fixed" not in prompt.lower()
    assert "not executed" not in prompt.lower()
    assert "do not write a Decision line." in prompt

    async def body():
        await record_evidence("lorient", met=True, facts={"distance_nm": 120})
        english = await review("lorient", reader=None, lang="en")
        assert seen["max_tokens"] == 400
        report = english["report"]
        justification = english["justification"]
        assert "decision field" not in report.lower()
        assert "not executed" not in report.lower()
        assert "advisory" not in report.lower()
        assert "The boat is" not in report
        assert "Arrival recorded at Lorient" in report
        assert report.lower().count("was reached") == 1
        assert ".." not in report and ".." not in justification
        assert report.lower().count("decision:") == 0
        assert justification.lower().count("decision:") == 1
        assert "Décision" not in justification
        await record_evidence("brest", met=True, facts={"distance_nm": 40})
        french = await review("brest", reader=None, lang="fr")
        french_report = french["report"]
        french_justification = french["justification"]
        assert "champ de décision" not in french_report.lower()
        assert "consultatif" not in french_report.lower()
        assert "pas exécuté" not in french_report.lower()
        assert "Le bateau est" not in french_report
        assert "L'arrivée est enregistrée à Lorient" in french_report
        assert "L'escale Brest est atteinte" in french_report
        assert french_report.lower().count("est atteinte") == 1
        assert ".." not in french_report and ".." not in french_justification
        assert french_report.lower().count("décision") == 0
        assert french_justification.lower().count("décision") == 1
        assert "Decision:" not in french_justification

    asyncio.run(body())


def test_code_writes_the_reached_sentence_with_a_formatted_date(monkeypatch):
    import app.core.llm as llm

    seen = {}

    async def fake_ask_text(prompt, system=None, **_kwargs):
        seen["prompt"] = prompt
        seen["system"] = system
        return "The treasurer alone decides. Evidence is a simulation."

    async def fake_ask_json(*_args, **_kwargs):
        return llm.LlmJson({"proposal": "capture", "reason": "met"}, "nim", "test-model", "{}")

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setattr(llm, "ask_json", fake_ask_json)

    async def body():
        await record_evidence(
            "lorient",
            met=True,
            facts={"arrival_iso": "2026-11-02T14:00:00Z", "distance_nm": 120},
        )
        english = await review("lorient", reader=None, lang="en")
        assert "recorded_at" not in seen["prompt"]
        assert "arrival_iso" not in seen["prompt"]
        assert '"language": "en"' in seen["prompt"]
        assert "Write in English only." in seen["system"]
        assert "Milestone Lorient was reached on 2 November 2026 at 14:00 UTC" in english["report"]
        assert "no remaining distance" in english["report"]
        await record_evidence(
            "dakar",
            met=True,
            facts={"arrival_iso": "2026-11-02T14:00:00Z"},
        )
        french = await review("dakar", reader=None, lang="fr")
        assert "L'escale Dakar est atteinte le 2 novembre 2026 à 14:00 UTC" in french["report"]
        assert "was reached" not in french["report"]

    asyncio.run(body())


def test_wrong_language_retries_then_uses_the_fallback(monkeypatch):
    import app.core.llm as llm

    systems = []

    async def fake_ask_text(prompt, system=None, **_kwargs):
        systems.append(system or "")
        return "Le modèle écrit seulement en français pour ce port."

    async def fake_ask_json(*_args, **_kwargs):
        return llm.LlmJson({"proposal": "wait", "reason": "later"}, "nim", "test-model", "{}")

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setattr(llm, "ask_json", fake_ask_json)

    async def body():
        await record_evidence("lorient", met=False, facts={"port": "Lorient"})
        result = await review("lorient", reader=None, lang="en")
        assert len(systems) == 2
        assert "Write in English only." in systems[0]
        assert "English" in systems[1]
        assert result["model_source"] == {"provider": "rules", "model": ""}
        assert "Milestone Lorient" in result["report"]
        assert "seulement en français" not in result["report"]
        assert "Jalon" not in result["report"]

    asyncio.run(body())


def test_displayed_ports_are_capitalized():
    assert captain.display_name("lorient") == "Lorient"
    assert captain.display_name("dakar") == "Dakar"
    assert captain.display_name("dep-mayotte") == "Mayotte"
    assert not captain.display_name("dep-mayotte").casefold().startswith("dep-")
    assert captain.display_name("dep-fort-de-france") == "Fort-de-France"
    assert captain.display_name("pointe-a-pitre") == "Pointe-à-Pitre"
    assert "dep-" not in captain.display_name("dep-fort-de-france").lower()

    async def body():
        french = await chat("Je parraine 20 milles près de Dakar")
        assert "Dakar" in french["reply"]
        assert french["suggested_pledge"]["milestone_id"] == "dep-dakar"
        english = await chat("I'd like to sponsor 20 nautical miles near Lorient")
        assert "Lorient" in english["reply"]
        assert "lorient" not in english["reply"]
        assert english["suggested_pledge"]["milestone_id"] == "dep-lorient"

    asyncio.run(body())


def test_a_port_dinner_counts_as_the_computed_pledge(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return "Pledge 310.00 EUR for 250 sponsored miles and a port dinner, Dakar, AUTHORIZE."

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        result = await chat("I'd like to sponsor 250 mi + dinner near Dakar")
        reply = result["reply"]
        assert result["suggested_pledge"]["description"] == "250 sponsored miles and port dinner"
        assert reply.count("Computed pledge") == 1
        assert "310.00 EUR" in reply
        assert "a port dinner" in reply

    asyncio.run(body())


def test_lightning_french_translates_english_labels(monkeypatch):
    import app.core.llm as llm

    class Answer:
        def __init__(self, text):
            self.text = text
            self.provider = "nim_fallback"
            self.model = "nvidia/nemotron-3.5-lightning-30b-a3b"

    async def fake_ask_text(*_args, **_kwargs):
        return Answer("Promesse notée. Milestone: Dakar. Intent: AUTHORIZE. Jalon: suite.")

    async def english_answer(*_args, **_kwargs):
        return Answer("Noted for the pledge. Milestone: Lorient. Intent: AUTHORIZE.")

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        french = await chat("Je parraine 10 milles près de Dakar")
        reply = french["reply"]
        assert french["model_source"]["provider"] == "nim_fallback"
        assert "Jalon : Dakar" not in reply
        assert "Jalon : suite" in reply
        assert "Promesse calculée" in reply
        assert "AUTHORIZE" not in reply
        assert "Milestone" not in reply
        assert "Intent:" not in reply
        monkeypatch.setattr(llm, "ask_text", english_answer)
        english = await chat("I'd like to sponsor 10 nautical miles near Lorient")
        assert "Noted for the pledge" in english["reply"]
        assert "Milestone:" not in english["reply"]
        assert "Jalon" not in english["reply"]

    asyncio.run(body())


def test_arrival_phrase_uses_arrived_not_the_registration_clock():
    evidence = {
        "recorded_at": "1999-01-01T00:00:00Z",
        "facts": {"arrived": "2026-11-02T14:00:00Z", "distance_nm": 120},
    }
    assert captain.arrival_phrase(evidence, "en") == "on 2 November 2026 at 14:00 UTC"
    assert captain.arrival_phrase(evidence, "fr") == "le 2 novembre 2026 à 14:00 UTC"
    assert "1999" not in captain.arrival_phrase(evidence, "fr")
    first = {"facts": {"arrived": "2026-11-01"}}
    assert captain.arrival_phrase(first, "fr") == "le 1er novembre 2026"
    assert captain.arrival_phrase({"facts": {"arrival_iso": "2026-11-02"}}, "en") == "on 2 November 2026"
    hidden = captain._evidence_for_model(evidence)
    assert "recorded_at" not in hidden
    assert "arrived" not in hidden.get("facts", {})


def test_reached_fact_is_stated_once_when_the_model_paraphrases(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return (
            "The leg is reached and complete. Arrival was recorded on 2026-11-02. "
            "The NAVIGUIDE simulation evidence covers 120 nautical miles. "
            "It was reached again."
        )

    async def fake_ask_json(*_args, **_kwargs):
        return llm.LlmJson({"proposal": "capture", "reason": "met"}, "nim", "test-model", "{}")

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setattr(llm, "ask_json", fake_ask_json)

    async def body():
        await record_evidence(
            "lorient",
            met=True,
            facts={"arrived": "2026-11-02T14:00:00Z", "distance_nm": 120},
        )
        result = await review("lorient", reader=None, lang="en")
        report = result["report"]
        assert report.lower().count("was reached") == 1
        assert report.startswith(
            "Milestone Lorient was reached on 2 November 2026 at 14:00 UTC, "
            "with no remaining distance."
        )
        assert "The NAVIGUIDE simulation evidence covers 120 nautical miles." in report
        assert "2026-11-02" not in report

    asyncio.run(body())


def test_forced_french_review_retries_then_falls_back(monkeypatch):
    import app.core.llm as llm

    systems = []

    async def fake_ask_text(prompt, system=None, **_kwargs):
        systems.append(system or "")
        return "The treasurer alone decides. This evidence is a simulation."

    async def fake_ask_json(*_args, **_kwargs):
        return llm.LlmJson({"proposal": "wait", "reason": "later"}, "nim", "test-model", "{}")

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setattr(llm, "ask_json", fake_ask_json)

    async def body():
        await record_evidence(
            "lorient",
            met=True,
            facts={"arrived": "2026-11-02T14:00:00Z", "distance_nm": 120},
        )
        result = await review("lorient", reader=None, lang="fr")
        assert len(systems) == 2
        assert "RAPPEL : écris en français uniquement." in systems[1]
        assert "Réponds uniquement en français" in systems[0]
        assert result["model_source"] == {"provider": "rules", "model": ""}
        assert result["report"].startswith(
            "L'escale Lorient est atteinte le 2 novembre 2026 à 14:00 UTC"
        )

    asyncio.run(body())


def test_forced_english_review_matches_the_reference_sentence(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return (
            "Lorient was reached on 2026-11-02 at 14:00. "
            "The NAVIGUIDE simulation evidence covers 120 nautical miles."
        )

    async def fake_ask_json(*_args, **_kwargs):
        return llm.LlmJson({"proposal": "capture", "reason": "met"}, "nim", "test-model", "{}")

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setattr(llm, "ask_json", fake_ask_json)

    async def body():
        await record_evidence(
            "lorient",
            met=True,
            facts={"arrived": "2026-11-02T14:00:00Z", "distance_nm": 120},
        )
        result = await review("lorient", reader=None, lang="en")
        assert result["report"] == (
            "Milestone Lorient was reached on 2 November 2026 at 14:00 UTC, "
            "with no remaining distance. "
            "The NAVIGUIDE simulation evidence covers 120 nautical miles."
        )

    asyncio.run(body())


def test_leg_name_is_a_prefix_not_a_filler_sentence(monkeypatch):
    import app.core.llm as llm

    replies = [
        "La preuve NAVIGUIDE est une simulation pour cette escale. Dakar is 80 nautical miles away.",
        "The NAVIGUIDE simulation evidence covers 80 nautical miles. Dakar is 80 nautical miles away.",
    ]

    async def fake_ask_text(*_args, **_kwargs):
        return replies.pop(0)

    async def fake_ask_json(*_args, **_kwargs):
        return llm.LlmJson({"proposal": "wait", "reason": "open"}, "nim", "test-model", "{}")

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setattr(llm, "ask_json", fake_ask_json)

    async def body():
        await record_evidence("dakar", met=False, facts={"distance_nm": 80})
        french = await review("dakar", reader=None, lang="fr")
        assert french["report"].startswith("Escale Dakar : la preuve NAVIGUIDE")
        assert "Jalon Dakar." not in french["report"]
        assert "miles away" not in french["report"].lower()
        assert "à 80 milles" not in french["report"]
        english = await review("dakar", reader=None, lang="en")
        assert english["report"].startswith(
            "Milestone Dakar: The NAVIGUIDE simulation evidence covers 80 nautical miles."
        )
        assert "Jalon Dakar." not in english["report"]
        assert "miles away" not in english["report"].lower()

    asyncio.run(body())


def test_french_chat_translates_milestone_and_intent(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return "Le milestone est noté. Intent: AUTHORIZE pour Dakar."

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        result = await chat("Je parraine 10 milles près de Dakar")
        reply = result["reply"]
        assert result["model_source"]["provider"] == "llm"
        assert "jalon" in reply.casefold()
        assert "intention : autorisation" in reply.casefold()
        assert not re.search(r"\bmilestone\b", reply, re.I)
        assert not re.search(r"\bintent\b", reply, re.I)

    asyncio.run(body())


def test_french_pledge_line_is_not_repeated(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return "Promesse calculée, sans débit : 120 milles parrainés (120,00 €), lorien, AUTHORIZE."

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        result = await chat("Je parraine 120 milles près de Lorien")
        reply = result["reply"]
        assert result["suggested_pledge"]["milestone_id"] == "dep-lorient"
        assert reply.count("Promesse calculée") == 1
        assert "Lorient" in reply
        assert not re.search(r"\blorien\b", reply, re.I)

    asyncio.run(body())


def test_chat_strips_invented_signatures(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return (
            "Voici la promesse. Capitaine de l'Escales Bleue. "
            "Signé,. Je m'appelle Blue Intelligence Escales."
        )

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        result = await chat("Je parraine 10 milles près de Brest")
        reply = result["reply"]
        assert "Escales Bleue" not in reply
        assert "Signé" not in reply
        assert "Je m'appelle" not in reply
        assert reply.count("— Le capitaine") == 1

    asyncio.run(body())


def test_english_pledge_mentions_intent_authorize():
    async def body():
        result = await chat("I'd like to sponsor 120 nautical miles near Lorient")
        assert "intent AUTHORIZE" in result["reply"]
        assert "120 sponsored miles" in result["reply"]

    asyncio.run(body())


def test_french_pledge_matches_amount_and_port_without_the_description(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return "Pour Lorient le total est 120,00 €. Votre intention est AUTHORIZE, sans reprendre le libellé."

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        result = await chat("Je parraine 120 milles près de Lorient")
        reply = result["reply"]
        assert "Pour Lorient le total est" in reply
        assert reply.lower().count("promesse calculée") == 1
        assert reply.lower().count("120 milles parrainés") == 1
        assert reply.lower().count("intention") == 1
        assert "intention : autorisation" in reply.casefold()
        assert "AUTHORIZE" not in reply

    asyncio.run(body())


def test_verbless_bleu_signature_is_removed(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return "Le montant est noté. Capitaine Bleu Intelligence Escales"

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        result = await chat("Je parraine 10 milles près de Brest")
        reply = result["reply"]
        assert "Bleu Intelligence" not in reply
        assert "Capitaine Bleu" not in reply
        assert "noté" in reply
        assert reply.count("— Le capitaine") == 1

    asyncio.run(body())


def test_membership_link_closes_the_sentence_when_text_continues(monkeypatch):
    import app.core.llm as llm

    url = "https://www.helloasso.com/associations/blue-intelligence/adhesions/membre"
    monkeypatch.setenv("HELLOASSO_MEMBERSHIP_URL", url)

    async def fake_ask_text(*_args, **_kwargs):
        return f"Le lien est {url} et le détail suit, 10,00 €, Brest, autorisation."

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        result = await chat("Je parraine 10 milles près de Brest")
        reply = result["reply"]
        assert f"{url}." in reply
        assert f"{url} et" not in reply

    asyncio.run(body())


def test_bare_arrival_is_kept_and_a_dated_sentence_is_dropped(monkeypatch, caplog):
    import logging

    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return (
            "The NAVIGUIDE simulation evidence records the arrival and covers 120 nautical miles. "
            "Logged on 2026-11-02T14:00:00Z."
        )

    async def fake_ask_json(*_args, **_kwargs):
        return llm.LlmJson({"proposal": "capture", "reason": "met"}, "nim", "test-model", "{}")

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setattr(llm, "ask_json", fake_ask_json)

    async def body():
        await record_evidence(
            "lorient",
            met=True,
            facts={"arrived": "2026-11-02T14:00:00Z", "distance_nm": 120},
        )
        with caplog.at_level(logging.WARNING, logger="escales.captain"):
            result = await review("lorient", reader=None, lang="en")
        assert result["model_source"]["provider"] == "llm"
        assert "arrival" in result["report"].lower()
        assert "2026-11-02" not in result["report"]
        assert "Milestone Lorient was reached on 2 November 2026 at 14:00 UTC" in result["report"]
        assert "rejected" not in caplog.text

    asyncio.run(body())


def test_rejected_report_logs_the_raw_reply(monkeypatch, caplog):
    import logging

    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return "Le trésorier seul décide pour cette preuve."

    async def fake_ask_json(*_args, **_kwargs):
        return llm.LlmJson({"proposal": "wait", "reason": "later"}, "nim", "test-model", "{}")

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setattr(llm, "ask_json", fake_ask_json)

    async def body():
        await record_evidence("lorient", met=True, facts={"distance_nm": 120})
        with caplog.at_level(logging.WARNING, logger="escales.captain"):
            result = await review("lorient", reader=None, lang="en")
        assert result["model_source"]["provider"] == "rules"
        assert "Le trésorier seul décide pour cette preuve." in caplog.text
        assert "language" in caplog.text
        assert "rejected" in caplog.text

    asyncio.run(body())


def test_dakar_not_reached_filters_distance_left(monkeypatch):
    import app.core.llm as llm

    french = captain._report_system("dakar", reached=False, lang="fr")
    english = captain._report_system("dakar", reached=False, lang="en")
    assert "en route vers Dakar" in french
    assert "jamais « à Dakar »" in french
    assert "heading toward Dakar" in english
    assert not re.search(r"\bis toward\b", english)

    replies = [
        "Nous avons parcouru 80 milles nautiques à Dakar. La preuve NAVIGUIDE est une simulation.",
        "It remains 80 nautical miles. The boat is 80 miles from Dakar. The NAVIGUIDE simulation covers the leg.",
    ]

    async def fake_ask_text(*_args, **_kwargs):
        return replies.pop(0)

    async def fake_ask_json(*_args, **_kwargs):
        return llm.LlmJson({"proposal": "wait", "reason": "open"}, "nim", "test-model", "{}")

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setattr(llm, "ask_json", fake_ask_json)

    async def body():
        await record_evidence("dakar", met=False, facts={"distance_nm": 80})
        french_report = await review("dakar", reader=None, lang="fr")
        assert "milles nautiques à Dakar" not in french_report["report"]
        assert "Escale Dakar : la preuve" in french_report["report"]
        english_report = await review("dakar", reader=None, lang="en")
        text = english_report["report"]
        assert "remains" not in text.lower()
        assert "miles from" not in text.lower()
        assert "NAVIGUIDE simulation covers the leg" in text

    asyncio.run(body())


def test_french_reply_standardises_intention_and_the_treasurer(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return "The treasurer et Le Trésorier valident. Votre intention est AUTHORIZE pour Brest, 10,00 €."

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        result = await chat("Je parraine 10 milles près de Brest")
        reply = result["reply"]
        assert "intention : autorisation" in reply.casefold()
        assert "AUTHORIZE" not in reply
        assert "The treasurer" not in reply
        assert "Le Trésorier" not in reply
        assert "le trésorier" in reply
        assert reply.lower().count("promesse calculée") == 1

    asyncio.run(body())


def test_english_report_keeps_a_tie_and_accepts_naviguide_miles(monkeypatch):
    import app.core.llm as llm

    sample = "NAVIGUIDE simulation reports 120 nautical miles covered at Lorient."
    assert captain._report_language(sample) == "en"
    assert captain._report_language(sample, "en") == "en"
    assert captain._report_language("Lorient.", "en") == "en"
    assert captain._report_language("Lorient.", "fr") == "fr"
    assert captain._report_language("Le trésorier seul décide pour cette preuve.", "en") == "fr"

    async def fake_ask_text(*_args, **_kwargs):
        return sample

    async def fake_ask_json(*_args, **_kwargs):
        return llm.LlmJson({"proposal": "capture", "reason": "met"}, "nim", "test-model", "{}")

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setattr(llm, "ask_json", fake_ask_json)

    async def body():
        await record_evidence("lorient", met=True, facts={"distance_nm": 120})
        result = await review("lorient", reader=None, lang="en")
        assert result["model_source"]["provider"] == "llm"
        assert "simulation reports 120 nautical miles covered at Lorient" in result["report"]
        assert "Milestone Lorient was reached" in result["report"]

    asyncio.run(body())


def test_reached_leg_keeps_miles_covered_from_the_port(monkeypatch):
    import app.core.llm as llm

    sentence = "The vessel covered 120 nautical miles from Lorient."

    async def fake_ask_text(*_args, **_kwargs):
        return sentence

    async def fake_ask_json(*_args, **_kwargs):
        return llm.LlmJson({"proposal": "capture", "reason": "met"}, "nim", "test-model", "{}")

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setattr(llm, "ask_json", fake_ask_json)

    async def body():
        await record_evidence("lorient", met=True, facts={"distance_nm": 120})
        result = await review("lorient", reader=None, lang="en")
        assert "120 nautical miles to Lorient" in result["report"]
        assert "miles from" not in result["report"].lower()
        assert "Milestone Lorient was reached" in result["report"]
        assert result["model_source"]["provider"] == "llm"

    asyncio.run(body())


def test_not_reached_prompt_says_heading_toward_and_rewrites_is_toward(monkeypatch):
    import app.core.llm as llm

    prompt = captain._report_system("lorient", reached=False, lang="en")
    assert "heading toward Lorient" in prompt
    assert not re.search(r"\bis toward\b", prompt)
    assert captain._heading_toward("The boat is toward Lorient.") == "The boat is heading toward Lorient."
    assert captain._heading_toward("The boat is heading toward Lorient.") == (
        "The boat is heading toward Lorient."
    )

    async def fake_ask_text(*_args, **_kwargs):
        return "The boat is toward Lorient. NAVIGUIDE simulation covers the leg."

    async def fake_ask_json(*_args, **_kwargs):
        return llm.LlmJson({"proposal": "void", "reason": "open"}, "nim", "test-model", "{}")

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setattr(llm, "ask_json", fake_ask_json)

    async def body():
        await record_evidence("lorient", met=False, facts={"distance_nm": 120})
        result = await review("lorient", reader=None, lang="en")
        assert "is heading toward Lorient" in result["report"]
        assert not re.search(r"\bis toward\b", result["report"])
        assert "NAVIGUIDE simulation covers the leg" in result["report"]

    asyncio.run(body())


def test_distorted_port_names_map_when_close():
    assert captain._canonical_slug("lorien") == "lorient"
    assert captain._canonical_slug("lorain") == "lorient"
    assert captain._canonical_slug("dakra") == "dakar"
    assert captain._canonical_slug("best") is None
    assert captain._canonical_slug("orain") is None
    pledge = captain.suggest_pledge("Je parraine 10 milles près de Lorain")
    assert pledge["milestone_id"] == "dep-lorient"
    shown = captain._fix_port_typos("Left lorain, then Lorien, for Dakar.")
    assert shown == "Left Lorient, then Lorient, for Dakar."
    assert "best" in captain._fix_port_typos("The best evidence stands.")


def test_pledge_amount_without_the_port_is_replaced(monkeypatch):
    import app.core.llm as llm

    class Answer:
        def __init__(self, text):
            self.text = text
            self.provider = "nim_fallback"
            self.model = "nvidia/nemotron-3.5-lightning-30b-a3b"

    async def fake_ask_text(*_args, **_kwargs):
        return Answer(
            "Promesse notée : 20 milles parrainés (20,00 €), autorisation. Le ciel est clair."
        )

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        result = await chat("Je parraine 20 milles près de Dakar")
        reply = result["reply"]
        assert result["model_source"]["provider"] == "nim_fallback"
        assert reply.count("20,00 €") == 1
        assert "Dakar" in reply
        assert "Promesse calculée, sans débit" in reply
        assert "Promesse notée" not in reply
        assert "Le ciel est clair" in reply

    asyncio.run(body())


def test_short_french_report_keeps_a_tie(monkeypatch):
    import app.core.llm as llm

    sample = "Source simulation, distance parcourue 120 nm."
    assert captain._report_language(sample, "fr") == "fr"
    assert captain._report_language(sample, "en") == "en"
    assert captain._report_language("Lorient.", "fr") == "fr"

    async def fake_ask_text(*_args, **_kwargs):
        return sample

    async def fake_ask_json(*_args, **_kwargs):
        return llm.LlmJson({"proposal": "capture", "reason": "met"}, "nim", "test-model", "{}")

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setattr(llm, "ask_json", fake_ask_json)

    async def body():
        await record_evidence("lorient", met=True, facts={"distance_nm": 120})
        result = await review("lorient", reader=None, lang="fr")
        assert result["model_source"]["provider"] == "llm"
        assert "distance parcourue 120 nm" in result["report"]
        assert "L'escale Lorient est atteinte" in result["report"]

    asyncio.run(body())


def test_schedule_display_names_drop_the_dep_prefix():
    from app.escales.naviguide_bridge import local_schedule_export

    assert captain.display_name("pointe-a-pitre") == "Pointe-à-Pitre"
    assert captain.display_name("dep-pointe-a-pitre") == "Pointe-à-Pitre"
    assert captain.display_name("dep-fort-de-france") == "Fort-de-France"
    for item in local_schedule_export()["escales"]:
        shown = captain.display_name(item["milestone_id"])
        assert shown == item["name"]
        assert captain.display_name(item["slug"]) == item["name"]
        assert not shown.casefold().startswith("dep-")


def test_chat_maps_pointe_a_pitre_and_asks_when_unknown():
    async def body():
        for message in (
            "Je parraine 20 milles à Pointe-à-Pitre",
            "Je parraine 20 milles à pointe-a-pitre",
            "Je parraine 20 milles à Pointe a Pitre",
            "Je parraine 20 milles à POINTE-A-PITRE",
            "Je parraine 20 milles à pointeapitre",
        ):
            result = await chat(message)
            assert result["suggested_pledge"]["milestone_id"] == "dep-pointe-a-pitre-guadeloupe"
            assert "Pointe-à-Pitre" in result["reply"]
            assert "Unspecified" not in result["reply"]
            assert "unspecified" not in result["reply"]
        missing = await chat("Je parraine 20 milles")
        assert missing["suggested_pledge"] is None
        assert "Quelle escale" in missing["reply"]
        assert "Unspecified" not in missing["reply"]
        assert "unspecified" not in missing["reply"]
        assert "20,00" not in missing["reply"]
        assert "AUTHORIZE" not in missing["reply"]
        unknown = await chat("I'd like to sponsor 20 miles near Atlantis")
        assert unknown["suggested_pledge"] is None
        assert "Which escale" in unknown["reply"]
        assert "Unspecified" not in unknown["reply"]
        assert "20.00" not in unknown["reply"]

    asyncio.run(body())


def test_lightning_strips_instructions_and_repairs_sentences():
    raw = (
        "Mention membership only by repeating the URL you were given. "
        "La route est tracée. en route vers Dakar. distance_nm 120 planned_nm 200."
    )
    cleaned = captain._prepare_model_narrative(raw, "fr")
    assert "membership" not in cleaned.lower()
    assert "you were given" not in cleaned.lower()
    assert "distance_nm" not in cleaned
    assert "planned_nm" not in cleaned
    assert "Distance parcourue" in cleaned
    assert "distance prévue" in cleaned
    assert "En route vers Dakar" in cleaned
    english = captain._prepare_model_narrative(
        "The leg shows distance_nm and planned_nm.",
        "en",
    )
    assert "distance covered" in english
    assert "planned distance" in english
    assert "distance_nm" not in english


def test_fast_lightning_failure_logs_the_message(monkeypatch, caplog):
    import logging

    import app.core.llm as llm

    errors = [
        RuntimeError("nim_fallback empty nvapi-secretvalue"),
        RuntimeError("nim HTTP 429"),
    ]

    async def fake_ask_text(*_args, **_kwargs):
        raise errors.pop(0)

    async def empty_ask_text(*_args, **_kwargs):
        return ""

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        with caplog.at_level(logging.WARNING, logger="escales.captain"):
            failed = await chat("Je parraine 20 milles près de Dakar")
            limited = await chat("Je parraine 10 milles près de Brest")
        assert failed["model_source"]["provider"] == "rules"
        assert limited["model_source"]["provider"] == "rules"
        assert "nim_fallback empty" in caplog.text
        assert "nim HTTP 429" in caplog.text
        assert "nvapi-secretvalue" not in caplog.text
        assert "[redacted]" in caplog.text
        assert "captain llm failed in" in caplog.text

    asyncio.run(body())

    caplog.clear()
    monkeypatch.setattr(llm, "ask_text", empty_ask_text)

    async def quiet():
        with caplog.at_level(logging.WARNING, logger="escales.captain"):
            result = await chat("Je parraine 5 milles près de Lorient")
        assert result["model_source"]["provider"] == "rules"
        assert "captain llm failed" not in caplog.text

    asyncio.run(quiet())


def test_invented_captain_sentences_are_dropped(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return (
            "Voici le calcul. Je suis le capitaine des Escales. "
            "Escales Bleue. Escales Bleues. Je m'appelle Marin."
        )

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        result = await chat("Je parraine 10 milles près de Brest")
        reply = result["reply"]
        assert "Voici le calcul" in reply
        assert "Je suis le capitaine" not in reply
        assert "Escales Bleue" not in reply
        assert "Je m'appelle" not in reply
        assert reply.count("— Le capitaine") == 1

    asyncio.run(body())


def test_pledge_line_drops_milestone_and_intent_labels(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return "La mer est calme. Jalon : Dakar. Intention : autorisation."

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        result = await chat("Je parraine 10 milles près de Dakar")
        reply = result["reply"]
        assert "La mer est calme" in reply
        assert reply.count("Promesse calculée") == 1
        assert "Jalon :" not in reply
        assert "Intention :" not in reply

    asyncio.run(body())


def test_chat_capitalizes_the_treasurer_after_a_period(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return "La mer est calme. le trésorier reste consultatif."

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        result = await chat("Je parraine 10 milles près de Brest")
        assert ". Le trésorier" in result["reply"]

    asyncio.run(body())


def test_thin_french_report_gains_the_covered_miles_sentence(monkeypatch):
    import app.core.llm as llm

    prompt = captain._report_system("lorient", reached=False, lang="fr")
    assert "contient un verbe" in prompt

    async def fake_ask_text(*_args, **_kwargs):
        return "The treasurer alone decides."

    async def fake_ask_json(*_args, **_kwargs):
        return llm.LlmJson({"proposal": "wait", "reason": "open"}, "nim", "test-model", "{}")

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setattr(llm, "ask_json", fake_ask_json)

    async def body():
        await record_evidence("lorient", met=False, facts={"distance_nm": 120})
        result = await review("lorient", reader=None, lang="fr")
        assert result["model_source"]["provider"] == "rules"
        assert "La preuve NAVIGUIDE (simulation) indique 120 milles parcourus." in result["report"]

    asyncio.run(body())


def test_glued_period_is_split_and_duplicate_sentences_drop():
    raw = (
        "The boat sailed 250 nm.The boat is heading toward Dakar. "
        "The boat is heading toward Dakar."
    )
    text = captain._finish_text(raw)
    assert "250 nm. The boat" in text
    assert text.lower().count("heading toward dakar") == 1
    url = captain._finish_text("See www.helloasso.com today.")
    assert "www.helloasso.com" in url
    assert "www. Hello" not in url


def test_bare_distance_numbers_are_rejected(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return (
            "The distance covered is 40 and the planned distance is 110. "
            "The boat sailed 80 nautical miles."
        )

    async def fake_ask_json(*_args, **_kwargs):
        return llm.LlmJson({"proposal": "wait", "reason": "open"}, "nim", "test-model", "{}")

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)
    monkeypatch.setattr(llm, "ask_json", fake_ask_json)

    async def body():
        await record_evidence("dakar", met=False, facts={"distance_nm": 80, "planned_nm": 110})
        result = await review("dakar", reader=None, lang="en")
        report = result["report"]
        assert "80 nautical miles" in report
        assert " 40" not in report
        assert "110" not in report
        assert "nautical miles or nm" in captain._report_system("dakar", reached=False, lang="en")

    asyncio.run(body())


def test_standalone_intent_authorize_is_dropped_when_the_pledge_states_it(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return "The sea is calm. Intent AUTHORIZE."

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        result = await chat("I'd like to sponsor 10 nautical miles near Lorient")
        reply = result["reply"]
        sentences = re.split(r"(?<=[.!?])\s+", reply.strip())
        assert not any(re.fullmatch(r"intent\s*:?\s*authorize\.?", sentence.strip(), re.I) for sentence in sentences)
        assert reply.count("Computed pledge") == 1
        assert "The sea is calm" in reply

    asyncio.run(body())


def test_french_vocabulary_and_the_pledge_line(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return (
            "La trésorière parle de remboursement. "
            "Le prix est 10,00 € en euros pour Brest. "
            "Le trésorier décide si l'argent est prélevé."
        )

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        result = await chat("Je parraine 10 milles près de Brest")
        reply = result["reply"]
        assert "remboursement" not in reply.casefold()
        assert "trésorière" not in reply.casefold()
        assert "en euros" not in reply.casefold()
        assert "10,00 €" in reply
        assert "Seul le trésorier décide si l'argent est prélevé ou libéré." in reply
        assert reply.count("Promesse calculée") == 1

    asyncio.run(body())


def test_ui_labels_the_llm_proposal_as_advisory():
    root = Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "escales"
    badge = (root / "advisoryLabel.js").read_text(encoding="utf-8")
    screen = (root / "EscalesScheduler.jsx").read_text(encoding="utf-8")
    assert "Advisory" in badge
    assert 'label: "Advisory"' in badge
    assert "data-advisory" in screen
    assert "Advisory" in screen


def test_miles_and_dinner_stay_one_pledge_and_list_two_cart_lines():
    pledge = captain.suggest_pledge("250 mi + dinner 60 € près de Dakar")
    assert pledge["amount_eur"] == "310.00"
    assert pledge["description"] == "250 milles parrainés et dîner d'escale"
    assert pledge["intent"] == "AUTHORIZE"
    assert "kind" not in pledge
    cart = captain.pledge_cart("250 mi + dinner 60 € près de Dakar", "fr", pledge)
    assert cart["amount_eur"] == "310.00"
    assert cart["intent"] == "AUTHORIZE"
    assert [line["kind"] for line in cart["lines"]] == ["mile", "meal"]
    assert [line["amount_eur"] for line in cart["lines"]] == ["250.00", "60.00"]
    assert cart["lines"][0]["price_label"] == "simulated price"
    assert cart["lines"][0]["target_id"] == "dep-dakar"
    assert cart["available"] is False
    assert cart["eta"] is None
    assert "order_id" not in cart


def test_other_kinds_use_the_simulated_catalogue():
    night = captain.suggest_pledge("2 nuits près de Mayotte")
    assert night["amount_eur"] == "120.00"
    assert night["kind"] == "night"
    assert night["description"] == "2 nuits"
    assert "mille" not in night["description"]
    berth = captain.suggest_pledge("1 poste près de Fort-de-France")
    assert berth["amount_eur"] == "30.00"
    assert berth["kind"] == "berth"
    care = captain.suggest_pledge("un soin près de Mayotte")
    assert care["amount_eur"] == "40.00"
    assert care["kind"] == "care"
    cabin = captain.suggest_pledge("1 cabine près de Mayotte")
    assert cabin["amount_eur"] == "80.00"
    assert cabin["kind"] == "cabin_leg"
    both = captain.suggest_pledge("10 milles et 1 nuit près de Mayotte")
    assert both["amount_eur"] == "70.00"
    assert both["item"] == "mixed"
    assert "kind" not in both
    assert "milles parrainés" in both["description"]
    assert "1 nuit" in both["description"]
    fund = captain.suggest_pledge("fonds commun 25 euros près de Mayotte")
    assert fund["amount_eur"] == "25.00"
    assert fund["kind"] == "common_fund"
    assert "mille" not in fund["description"]
    project = captain.suggest_pledge("promesse projet 15 EUR près de Dakar")
    assert project["amount_eur"] == "15.00"
    assert project["kind"] == "project_pledge"
    english = captain.suggest_pledge("2 nights near Mayotte", lang="en")
    assert english["description"] == "2 nights"
    assert english["amount_eur"] == "120.00"


def test_cabin_cart_line_is_the_leg_and_stays_authorize():
    cabin = captain.suggest_pledge("1 cabine près de Fort-de-France")
    assert cabin["kind"] == "cabin_leg"
    assert cabin["amount_eur"] == "80.00"
    assert cabin["intent"] == "AUTHORIZE"
    cart = captain.pledge_cart("1 cabine près de Fort-de-France", "fr", cabin)
    line = cart["lines"][0]
    assert line["kind"] == "cabin_leg"
    assert line["intent"] == "AUTHORIZE"
    assert line["milestone_id"] == "leg-fort-de-france-martinique-to-pointe-a-pitre-guadeloupe"
    assert line["pledge"]["target_id"] == line["milestone_id"]
    assert line["pledge"]["kind"] == "cabin_leg"
    assert captain.display_name(line["milestone_id"]) == (
        "Fort-de-France (Martinique) → Pointe-à-Pitre (Guadeloupe)"
    )


def test_chat_cart_keeps_authorize_and_reads_clock_and_schedule(monkeypatch):
    monkeypatch.delenv("ESCALES_CLOCK_START", raising=False)

    async def body():
        mayotte = await chat("2 nuits près de Mayotte")
        cart = mayotte["cart"]
        assert cart["clock_start"] == "2026-11-12"
        from app.escales.naviguide_bridge import local_schedule_export

        route_mayotte = next(
            item for item in local_schedule_export()["escales"] if "mayotte" in item["slug"]
        )
        assert cart["eta"] == route_mayotte["arrival_iso"]
        assert cart["eta"] > "2026-11-12"
        assert cart["available"] is True
        assert cart["intent"] == "AUTHORIZE"
        assert cart["lines"][0]["kind"] == "night"
        assert cart["lines"][0]["quantity"] == "2"
        assert cart["amount_eur"] == mayotte["suggested_pledge"]["amount_eur"] == "120.00"
        assert "120,00 €" in mayotte["reply"]
        assert "order_id" not in mayotte
        assert mayotte["model_source"] == {"provider": "rules", "model": ""}
        english = await chat("I would like 2 nights near Mayotte")
        assert english["suggested_pledge"]["description"] == "2 nights"
        assert "120.00 EUR" in english["reply"]
        assert english["cart"]["available"] is True
        status = await chat("Quel est le statut ?")
        assert status["suggested_pledge"] is None
        assert status["cart"] is None
        mixed = await chat("250 mi + dinner 60 € près de Dakar")
        assert mixed["suggested_pledge"]["amount_eur"] == "310.00"
        assert mixed["cart"]["lines"][1]["kind"] == "meal"
        assert "310,00 €" in mixed["reply"]
        assert "250,00" not in mixed["reply"]

    asyncio.run(body())


def test_cart_lines_use_the_existing_authorize_pledge():
    async def body():
        result = await chat("250 mi + dinner 60 € près de Dakar")
        assert "order_id" not in result
        spy = Spy()
        saved = []
        for line in result["cart"]["lines"]:
            saved.append(await create_pledge(client=spy, **line["pledge"]))
        assert [doc["intent"] for doc in saved] == ["AUTHORIZE", "AUTHORIZE"]
        assert [doc["payment_mode"] for doc in saved] == ["AUTHORIZE", "AUTHORIZE"]
        assert [doc["status"] for doc in saved] == ["created", "created"]
        assert [doc["amount_eur"] for doc in saved] == ["250.00", "60.00"]
        assert [doc["kind"] for doc in saved] == ["mile", "meal"]
        assert [doc["target_id"] for doc in saved] == ["dakar", "dakar"]
        authorized = await authorize_pledge(saved[0]["_id"], spy)
        assert authorized["status"] == "authorized"
        assert [call[0] for call in spy.calls] == ["create", "create", "orders.get", "authorize"]

    asyncio.run(body())


def test_cette_nuit_and_tonight_are_not_a_night():
    french = captain.suggest_pledge("cette nuit près de Mayotte")
    assert french["kind"] == "mile"
    assert "nuit" not in french["description"]
    cart = captain.pledge_cart("cette nuit près de Mayotte", "fr", french)
    assert [line["kind"] for line in cart["lines"]] == ["mile"]
    both = captain.suggest_pledge("2 nuits cette nuit près de Mayotte")
    assert both["kind"] == "night"
    assert both["amount_eur"] == "120.00"
    assert both["description"] == "2 nuits"
    english = captain.suggest_pledge("tonight near Mayotte", lang="en")
    assert english["kind"] == "mile"
    assert "night" not in english["description"]
    english_cart = captain.pledge_cart("tonight near Mayotte", "en", english)
    assert [line["kind"] for line in english_cart["lines"]] == ["mile"]
    kept = captain.suggest_pledge("2 nights tonight near Mayotte", lang="en")
    assert kept["description"] == "2 nights"
    assert kept["amount_eur"] == "120.00"


def test_written_numbers_from_one_to_ten():
    french = (
        ("un", 1), ("deux", 2), ("trois", 3), ("quatre", 4), ("cinq", 5),
        ("six", 6), ("sept", 7), ("huit", 8), ("neuf", 9), ("dix", 10),
    )
    english = (
        ("one", 1), ("two", 2), ("three", 3), ("four", 4), ("five", 5),
        ("six", 6), ("seven", 7), ("eight", 8), ("nine", 9), ("ten", 10),
    )
    for word, count in french:
        pledge = captain.suggest_pledge(f"{word} nuits près de Mayotte")
        assert pledge["kind"] == "night"
        assert pledge["amount_eur"] == f"{count * 60:.2f}"
        assert pledge["description"] == ("1 nuit" if count == 1 else f"{count} nuits")
    for word, count in english:
        pledge = captain.suggest_pledge(f"{word} nights near Mayotte", lang="en")
        assert pledge["amount_eur"] == f"{count * 60:.2f}"
        assert pledge["description"] == ("1 night" if count == 1 else f"{count} nights")
    miles = captain.suggest_pledge("dix milles près de Dakar")
    assert miles["kind"] == "mile"
    assert miles["amount_eur"] == "10.00"
    assert miles["description"] == "10 milles parrainés"
    english_miles = captain.suggest_pledge("ten miles near Dakar", lang="en")
    assert english_miles["amount_eur"] == "10.00"
    assert english_miles["description"] == "10 sponsored miles"


def test_euros_for_the_project_is_a_project_pledge_line():
    text = "25 € pour le projet près de Dakar"
    pledge = captain.suggest_pledge(text)
    assert pledge["kind"] == "project_pledge"
    assert pledge["amount_eur"] == "25.00"
    assert "mille" not in pledge["description"]
    cart = captain.pledge_cart(text, "fr", pledge)
    assert [line["kind"] for line in cart["lines"]] == ["project_pledge"]
    assert cart["lines"][0]["amount_eur"] == "25.00"
    assert cart["lines"][0]["pledge"]["kind"] == "project_pledge"
    assert cart["lines"][0]["pledge"]["amount_eur"] == "25.00"
    words = captain.suggest_pledge("dix euros pour le projet près de Dakar")
    assert words["kind"] == "project_pledge"
    assert words["amount_eur"] == "10.00"


def test_code_enforces_the_fixed_treasurer_sentence(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return "The treasurer will decide. Le trésorier doit trancher."

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        result = await chat("Je parraine 10 milles près de Dakar")
        reply = result["reply"]
        sentence = "Seul le trésorier décide si l'argent est prélevé ou libéré."
        assert reply.count(sentence) == 1
        assert "will decide" not in reply.casefold()
        assert "trancher" not in reply.casefold()
        assert "The treasurer" not in reply

    asyncio.run(body())


def test_local_time_eta_for_dakar_lorient_and_pointe_a_pitre():
    assert captain._local_eta("dakar", {"arrival_iso": "2026-12-01T08:00:00+00:00"}) == (
        "2026-12-01T08:00:00+00:00"
    )
    assert captain._local_eta("lorient", {"arrival_iso": "2026-12-15T08:00:00+00:00"}) == (
        "2026-12-15T09:00:00+01:00"
    )
    pointe = captain.suggest_pledge("10 milles près de Pointe-à-Pitre")
    assert pointe["milestone_id"] == "dep-pointe-a-pitre-guadeloupe"
    cart = captain.pledge_cart("10 milles près de Pointe-à-Pitre", "fr", pointe)
    assert cart["available"] is True
    assert cart["eta"].endswith("-04:00")
    mayotte = captain.suggest_pledge("2 nuits près de Mayotte")
    assert mayotte["milestone_id"] == "dep-dzaoudzi-mayotte"
    mayotte_cart = captain.pledge_cart("2 nuits près de Mayotte", "fr", mayotte)
    assert mayotte_cart["eta"] > "2026-11-12"


def test_treasurer_sentence_is_added_when_the_model_omits_it(monkeypatch):
    import app.core.llm as llm

    async def fake_ask_text(*_args, **_kwargs):
        return "La mer est calme."

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        result = await chat("Je parraine 10 milles près de Dakar")
        reply = result["reply"]
        sentence = "Seul le trésorier décide si l'argent est prélevé ou libéré."
        assert reply.count(sentence) == 1
        assert "La mer est calme" in reply
        assert len(reply.split()) <= 80

    asyncio.run(body())


def test_charge_claim_falls_back_to_the_rules_text(monkeypatch):
    import app.core.llm as llm

    replies = [
        "Votre carte sera débitée demain. La mer est calme.",
        "The amount will be charged tonight. The sea is calm.",
    ]

    async def fake_ask_text(*_args, **_kwargs):
        return replies.pop(0)

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        french = await chat("Je parraine 10 milles près de Dakar")
        reply = french["reply"]
        assert "sera débit" not in reply.casefold()
        assert "Votre carte" not in reply
        assert "La mer est calme" not in reply
        assert "Seul le trésorier décide si l'argent est prélevé ou libéré." in reply
        assert "10,00 €" in reply
        assert "10 milles parrainés" in reply
        english = await chat("I'd like to sponsor 10 nautical miles near Lorient")
        english_reply = english["reply"]
        assert "charged" not in english_reply.casefold()
        assert "The sea is calm" not in english_reply
        assert "Only the treasurer decides whether the money is captured or released." in english_reply
        assert "10.00 EUR" in english_reply
        assert "10 sponsored miles" in english_reply

    asyncio.run(body())


def test_to_the_project_and_au_projet_are_project_pledges():
    phrases = (
        ("25 € au projet près de Dakar", "fr", "25.00"),
        ("20 EUR to the project near Dakar", "en", "20.00"),
        ("15 EUR towards the project near Dakar", "en", "15.00"),
    )
    for text, lang, amount in phrases:
        pledge = captain.suggest_pledge(text, lang=lang)
        assert pledge["kind"] == "project_pledge"
        assert pledge["amount_eur"] == amount
        cart = captain.pledge_cart(text, lang, pledge)
        assert [line["kind"] for line in cart["lines"]] == ["project_pledge"]
        assert cart["lines"][0]["amount_eur"] == amount
        assert cart["lines"][0]["pledge"]["kind"] == "project_pledge"


def test_return_from_europa_is_the_homeward_leg():
    """Direction, not the first port named, picks the Europa return."""
    expected = "leg-europa-taaf-to-la-rochelle"
    phrases = (
        "1 cabine pour le retour d'Europa",
        "1 cabine depuis Europa",
        "une cabine pour le retour Europa La Rochelle",
        "cabine depuis Europa vers La Rochelle",
        "1 cabin for the return from Europa",
    )
    for phrase in phrases:
        pledge = captain.suggest_pledge(phrase)
        assert pledge["kind"] == "cabin_leg", phrase
        assert pledge["milestone_id"] == expected, phrase
    outbound = captain.suggest_pledge("1 cabine près de La Rochelle")
    assert outbound["milestone_id"] == "leg-la-rochelle-to-ajaccio-corse"


def test_project_and_fund_without_a_port_keep_an_empty_milestone():
    project = captain.suggest_pledge("Je donne 15 euros au projet")
    assert project["kind"] == "project_pledge"
    assert project["milestone_id"] == ""
    assert project["target_id"] == "projet"
    fund = captain.suggest_pledge("15 euros au fonds commun")
    assert fund["kind"] == "common_fund"
    assert fund["milestone_id"] == ""
    assert fund["target_id"] == "fonds-commun"


def test_review_lists_pending_authorizations():
    async def body():
        spy = Spy()
        first = await create_pledge(
            amount_eur="20.00",
            description="20 milles",
            milestone_id="dep-mayotte",
            client=spy,
            client_key="rev-a",
        )
        await authorize_pledge(first["_id"], spy)
        second = await create_pledge(
            amount_eur="60.00",
            description="diner",
            milestone_id="dep-mayotte",
            client=spy,
            client_key="rev-b",
        )
        await authorize_pledge(second["_id"], spy)
        waiting = await create_pledge(
            amount_eur="10.00",
            description="pas encore",
            milestone_id="dep-mayotte",
            client=spy,
            client_key="rev-c",
        )
        other = await create_pledge(
            amount_eur="20.00",
            description="ailleurs",
            milestone_id="dakar",
            client=spy,
            client_key="rev-d",
        )
        await authorize_pledge(other["_id"], spy)
        await record_evidence("dep-mayotte", met=True, facts={"port": "Mayotte"})
        result = await review("dep-mayotte", reader=ReadOnlyTools(spy))
        pending = result["pending_authorizations"]
        assert [row["pledge_id"] for row in pending] == result["pledge_ids"]
        assert {row["pledge_id"] for row in pending} == {first["_id"], second["_id"]}
        assert waiting["_id"] not in result["pledge_ids"]
        assert other["_id"] not in result["pledge_ids"]
        by_id = {row["pledge_id"]: row for row in pending}
        assert by_id[first["_id"]]["authorization_id"] == f"AUTH-{first['order_id']}"
        assert by_id[first["_id"]]["amount_eur"] == "20.00"
        assert by_id[second["_id"]]["amount_eur"] == "60.00"
        assert all(row["status"] == "authorized" for row in pending)
        assert all(row["currency"] == "EUR" for row in pending)
        assert isinstance(by_id[first["_id"]]["authorization_age_days"], int)
        names = [call[0] for call in spy.calls]
        assert "capture" not in names
        assert "void" not in names
        assert (await require_pledge(first["_id"]))["status"] == "authorized"

    asyncio.run(body())


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


def test_fund_question_answers_from_the_fund_route_without_nim(monkeypatch):
    import app.core.llm as llm

    def refuse_nim(*_args, **_kwargs):
        raise AssertionError("NIM must stay behind the optional flag")

    monkeypatch.setattr(llm, "ask_text", refuse_nim)

    async def body():
        spy = Spy()
        await _captured_common_fund(spy, "12.00", "qa-boat")
        stop = await create_pledge(
            amount_eur="20.00",
            description="20 milles",
            milestone_id="dep-mayotte",
            client=spy,
            client_key="qa-stop",
        )
        await authorize_pledge(stop["_id"], spy)
        await capture_pledge(stop["_id"], spy)
        from app.escales.ledger import fund_for_milestone

        boat_fund = await fund_for_milestone("fund")
        mayotte_fund = await fund_for_milestone("mayotte")
        asked = await chat("Quel est le solde du fonds commun ?")
        assert asked["suggested_pledge"] is None
        assert asked["cart"] is None
        assert asked["fund"] == boat_fund
        assert asked["fund"]["income_eur"] == "12.00"
        assert "12,00" in asked["reply"]
        assert "20,00" not in asked["reply"]
        assert "999" not in asked["reply"]
        assert asked["model_source"] == {"provider": "rules", "model": ""}
        assert "Seul le trésorier" in asked["reply"]
        assert "— Le capitaine" in asked["reply"]
        local = await chat("Quel est le solde du fonds commun à Mayotte ?")
        assert local["fund"] == mayotte_fund
        assert "20,00" in local["reply"]
        assert "la caisse de Dzaoudzi (Mayotte)" in local["reply"]
        assert "fonds commun" not in local["reply"].casefold()
        assert local["model_source"]["provider"] == "rules"
        project = await chat("How much money is in the project fund?")
        assert project["suggested_pledge"] is None
        assert project["cart"] is None
        assert "Which escale" not in project["reply"]
        assert project["fund"]["milestone_id"] == "projet"
        assert "the project fund" in project["reply"].casefold()
        assert "0.00 EUR" in project["reply"]
        assert project["model_source"] == {"provider": "rules", "model": ""}
        english = await chat("What is the common fund balance?")
        assert "12.00 EUR" in english["reply"]
        assert english["fund"]["balance_eur"] == "12.00"
        assert english["model_source"] == {"provider": "rules", "model": ""}
        gift = await chat("15 euros au fonds commun")
        assert gift["suggested_pledge"]["kind"] == "common_fund"
        assert "fund" not in gift

    asyncio.run(body())


def test_fund_question_filters_invented_numbers(monkeypatch):
    import app.core.llm as llm

    class Faithful:
        text = "Income 12.00 EUR, spending 0.00 EUR, balance 12.00 EUR."
        provider = "nim"
        model = "nvidia/super"

    answers = {"text": Faithful()}

    async def fake_ask_text(*_args, **_kwargs):
        return answers["text"]

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        spy = Spy()
        await _captured_common_fund(spy, "12.00", "qa-filter")
        kept = await chat("What is the common fund balance?")
        assert kept["model_source"] == {"provider": "nim", "model": "nvidia/super"}
        assert "12.00 EUR" in kept["reply"]
        assert "999" not in kept["reply"]
        answers["text"] = "The balance is 999 EUR."
        fallen = await chat("What is the common fund balance?")
        assert "999" not in fallen["reply"]
        assert "[?]" not in fallen["reply"]
        assert "12.00 EUR" in fallen["reply"]
        assert fallen["model_source"] == {"provider": "rules", "model": ""}

    asyncio.run(body())
