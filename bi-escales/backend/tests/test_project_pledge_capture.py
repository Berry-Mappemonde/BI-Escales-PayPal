"""Project crowdfunding: CAPTURE intent, immediate debit, project fund balance."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.departure_clock import run_departure_clock
from app.escales.ledger import fund_for_milestone, list_finance_entries
from app.escales.pledges import authorize_pledge, create_pledge, get_ledger, reset_ledger
from app.escales.webhooks import _apply_event
from tests.test_escales_pledges import Spy


def test_project_pledge_capture_order_and_fund_balance():
    async def body():
        reset_ledger()
        spy = Spy()
        created = await create_pledge(
            amount_eur="25.00",
            description="École",
            milestone_id="",
            client=spy,
            kind="project_pledge",
            target_id="projet-ecole",
        )
        assert created["intent"] == "CAPTURE"
        assert created["payment_mode"] == "CAPTURE"
        assert any(call[0] == "create_capture" for call in spy.calls)
        assert not any(call[0] == "create" for call in spy.calls)
        captured = await authorize_pledge(created["_id"], spy)
        assert captured["status"] == "captured"
        assert ("orders.capture", created["order_id"]) in spy.calls
        captured_lines = [
            entry
            for entry in await list_finance_entries()
            if entry.get("kind") == "pledge_captured" and entry.get("pledge_id") == created["_id"]
        ]
        assert len(captured_lines) == 1
        assert captured_lines[0]["amount_eur"] == "25.00"
        fund = await fund_for_milestone("projet")
        assert fund["balance_eur"] == "25.00"

    asyncio.run(body())


def test_project_pledge_webhook_capture_from_created():
    async def body():
        reset_ledger()
        spy = Spy()
        created = await create_pledge(
            amount_eur="10.00",
            description="Projet",
            milestone_id="",
            client=spy,
            kind="project_pledge",
            target_id="projet-ecole",
        )
        pledge_id = created["_id"]
        order_id = created["order_id"]
        event = {
            "id": "WH-PROJ-CAP",
            "event_type": "PAYMENT.CAPTURE.COMPLETED",
            "resource": {
                "id": "CAP-PROJ-1",
                "status": "COMPLETED",
                "supplementary_data": {"related_ids": {"order_id": order_id}},
            },
        }
        result = await _apply_event(event)
        assert result.get("pledge_id") == pledge_id
        saved = await get_ledger().get_pledge(pledge_id)
        assert saved["status"] == "captured"
        assert saved.get("capture_id") == "CAP-PROJ-1"

    asyncio.run(body())


def test_departure_clock_ignores_captured_project_pledge(monkeypatch):
    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr("app.escales.departure_clock.refuse_early_authorization", noop)

    async def body():
        reset_ledger()
        spy = Spy()
        mile = await create_pledge(
            amount_eur="1.00",
            description="miles",
            milestone_id="dep-mayotte",
            client=spy,
            kind="mile",
            target_id="mayotte",
        )
        await authorize_pledge(mile["_id"], spy)
        project = await create_pledge(
            amount_eur="5.00",
            description="gift",
            milestone_id="dep-mayotte",
            client=spy,
            kind="project_pledge",
            target_id="projet-ecole",
        )
        await authorize_pledge(project["_id"], spy)
        assert (await get_ledger().get_pledge(project["_id"]))["status"] == "captured"
        result = await run_departure_clock(spy)
        mile_action = next(a for a in result["actions"] if a["pledge_id"] == mile["_id"])
        assert mile_action["action"] in {"wait", "capture", "void"}
        project_actions = [a for a in result["actions"] if a["pledge_id"] == project["_id"]]
        assert project_actions == []

    asyncio.run(body())
