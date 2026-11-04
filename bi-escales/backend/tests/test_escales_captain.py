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
from app.escales.pledges import authorize_pledge, create_pledge, get_ledger, require_pledge, reset_ledger
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
        assert "Promesse calculée" not in result["reply"]
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
            return "The price is 120,00 €. 120 sponsored miles, lorient, AUTHORIZE."
        return "Le montant est 120.00 EUR. 120 milles parrainés, Lorient, AUTHORIZE."

    monkeypatch.setattr(llm, "has_llm", lambda settings=None: True)
    monkeypatch.setattr(llm, "ask_text", fake_ask_text)

    async def body():
        french = await chat("Je voudrais parrainer 120 milles près de Lorient")
        assert "120,00 €" in french["reply"]
        assert "120.00" not in french["reply"]
        assert "120 milles parrainés" in french["reply"]
        assert "Promesse calculée" not in french["reply"]
        english = await chat("I'd like to sponsor 120 nautical miles near Lorient")
        assert "120.00 EUR" in english["reply"]
        assert "120,00" not in english["reply"]
        assert "€" not in english["reply"]
        assert "120 sponsored miles" in english["reply"]
        assert "milles parrainés" not in english["reply"]
        assert "Computed pledge" not in english["reply"]

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
        assert "brest" in reply

    asyncio.run(body())


def test_suggest_pledge_adds_every_item_in_the_message():
    pledge = captain.suggest_pledge("250 mi + dinner 60 € près de Dakar")
    assert pledge["amount_eur"] == "310.00"
    assert pledge["currency"] == "EUR"
    assert pledge["milestone_id"] == "dakar"
    assert pledge["intent"] == "AUTHORIZE"
    assert "milles parrainés" in pledge["description"]
    assert "dîner" in pledge["description"].lower()
    assert "sponsored" not in pledge["description"]
    english = captain.suggest_pledge("250 mi + dinner 60 € near Dakar", lang="en")
    assert english["amount_eur"] == "310.00"
    assert english["milestone_id"] == "dakar"
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
    assert "Milestone lorient" in english
    french = captain._fallback_report("lorient", "wait", evidence, lang="fr")
    assert "Jalon lorient" in french
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
    kept = captain.validate_advisory_proposal("void", "milestone not met", age_days=28)
    assert kept["proposal"] == "void"
    assert kept["reason"] == "milestone not met"
    assert kept["dropped"] is False
    assert kept["advisory"] is True
    older = captain.validate_advisory_proposal(
        "reauthorize",
        "the 29-day authorization has expired",
        age_days=29,
    )
    assert older["proposal"] == "reauthorize"
    assert older["authorization_valid"] is False
    assert older["advisory"] is True


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
        result = await review("dep-mayotte", reader=None)
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


def test_ui_labels_the_llm_proposal_as_advisory():
    root = Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "escales"
    badge = (root / "advisoryLabel.js").read_text(encoding="utf-8")
    screen = (root / "EscalesScheduler.js").read_text(encoding="utf-8")
    assert "Advisory" in badge
    assert 'label: "Advisory"' in badge
    assert "data-advisory" in screen
    assert "Advisory" in screen
