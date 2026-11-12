"""The Captain's review reads the NAVIGUIDE logbook itself (review card B4).

The card's "What the Captain looked at" quotes the logbook, so the review must
read it server-side, from the same source GET /schedule publishes, and cut it at
the review clock. Dates below come from the local schedule export that test2
serves (``"source": "local"``): Ajaccio arrives 2026-11-29T02:02:52Z, with
logbook positions 48 h and 12 h before.
"""
import asyncio
import json
from unittest.mock import Mock

import pytest

from app.escales import ledger
from app.escales.captain import review
from app.escales.naviguide_bridge import clock_legs
from app.escales.toolkit_tools import ReadOnlyTools
from app.routers import escales as escales_router


@pytest.fixture
def reader(monkeypatch):
    monkeypatch.setenv("ESCALES_TOOLKIT_ENABLED", "0")
    monkeypatch.setattr(ledger, "_ledger", ledger.MemoryLedger())
    from app.core import llm

    monkeypatch.setattr(llm, "has_llm", lambda *a, **kw: False)
    return ReadOnlyTools(Mock())


def _published_logbook(milestone_id):
    """The stop's logbook exactly as GET /schedule returns it."""
    body = asyncio.run(escales_router.get_schedule())
    return body["logbook"][milestone_id]


def _reads(result):
    return {call["tool"]: call for call in result["naviguide_tool_calls"]}


def test_review_returns_the_logbook_entries_reached_at_its_clock(reader, monkeypatch):
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-28T15:00:00+00:00")
    published = _published_logbook("dep-ajaccio-corse")
    result = asyncio.run(review("dep-ajaccio-corse", reader=reader, lang="en"))

    # The two positions are behind the clock; the arrival on the 29th is not.
    assert result["logbook"] == published[:2]
    assert [entry["t"] for entry in result["logbook"]] == ["2026-11-27T02:02:52Z", "2026-11-28T14:02:52Z"]
    assert result["logbook"][-1]["label_en"] == "Position — underway for Ajaccio (Corse)"
    assert result["at"] == "2026-11-28T15:00:00+00:00"
    assert _reads(result)["logbook.read"] == {
        "tool": "logbook.read",
        "resource_id": "dep-ajaccio-corse",
        "read_only": True,
        "status": "ok",
        "entries": 2,
    }


def test_review_carries_the_eta_it_used(reader, monkeypatch):
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-12T08:00:00+00:00")
    result = asyncio.run(review("dep-ajaccio-corse", reader=reader, lang="en"))
    assert result["naviguide_eta"]["arrival_iso"] == "2026-11-29T02:02:52+00:00"
    assert _reads(result)["schedule.eta"]["read_only"] is True


def test_before_any_entry_the_review_says_it_read_an_empty_logbook(reader, monkeypatch):
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-12T08:00:00+00:00")
    result = asyncio.run(review("dep-ajaccio-corse", reader=reader, lang="fr"))
    assert result["logbook"] == []
    assert _reads(result)["logbook.read"]["entries"] == 0


def test_the_stored_proposal_keeps_the_logbook(reader, monkeypatch):
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-12T13:00:00+00:00")

    async def run():
        result = await review("dep-la-rochelle", reader=reader, lang="en")
        stored = await ledger.get_ledger().get_milestone("dep-la-rochelle")
        return result, stored

    result, stored = asyncio.run(run())
    assert [entry["kind"] for entry in result["logbook"]] == ["stop"]
    assert result["logbook"][0]["label_en"] == "Stopover — arrival at La Rochelle"
    assert stored["proposal"]["logbook"] == result["logbook"]


def test_a_cabin_leg_has_no_logbook_to_read(reader, monkeypatch):
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-12T08:00:00+00:00")
    leg = clock_legs()[0]["id"]
    result = asyncio.run(review(leg, reader=reader, lang="en"))
    assert "logbook" not in result
    assert "logbook.read" not in _reads(result)


def test_the_model_reads_the_logbook_without_its_dates(reader, monkeypatch):
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-28T15:00:00+00:00")
    from app.core import llm

    prompts = []

    async def ask_text(prompt, **kwargs):
        prompts.append(prompt)
        return "The boat is heading toward Ajaccio (Corse). The logbook records it underway."

    async def ask_json(*args, **kwargs):
        raise RuntimeError("no advisory in this test")

    monkeypatch.setattr(llm, "has_llm", lambda *a, **kw: True)
    monkeypatch.setattr(llm, "ask_text", ask_text)
    monkeypatch.setattr(llm, "ask_json", ask_json)
    asyncio.run(review("dep-ajaccio-corse", reader=reader, lang="fr"))

    sent = json.loads(prompts[0])
    assert sent["logbook"] == [
        {"kind": "position", "entry": "Position — en route vers Ajaccio (Corse)"},
        {"kind": "position", "entry": "Position — en route vers Ajaccio (Corse)"},
    ]
    assert "2026-11-27" not in json.dumps(sent["logbook"])
