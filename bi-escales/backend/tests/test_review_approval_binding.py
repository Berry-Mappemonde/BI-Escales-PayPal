"""B17: only an approved capture verdict after the calendar anchor permits capture."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales import ledger as ledger_module
from app.escales.config import simulated_now
from app.escales.milestones import captain_review_approved
from app.escales.pledges import get_ledger, reset_ledger
from app.routers.escales import router, set_paypal_client_factory
from tests.test_escales_router import FakePayPal
from tests.test_escales_vault_enable import _VaultClockFake

ADMIN = {"x-admin-key": "b17-admin"}
ARRIVAL = "2026-11-29T08:00:00+00:00"
DEPARTURE = "2026-12-02T08:00:00+00:00"
MID = "dep-b17-stop"
PID = "b17-pledge"


@pytest.fixture(params=["memory", "mongo"])
def api(request, monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "b17-admin")
    monkeypatch.setenv("ESCALES_LLM_ENABLED", "0")
    reset_ledger()
    if request.param == "mongo":
        from mongomock_motor import AsyncMongoMockClient
        monkeypatch.setattr(ledger_module, "_ledger", ledger_module.MongoLedger(AsyncMongoMockClient().b17))
    fake = FakePayPal()
    set_paypal_client_factory(lambda: fake)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client, fake
    set_paypal_client_factory(None)
    reset_ledger()


def seed(*, cabin=False, vault=False):
    async def run():
        await get_ledger().ensure_milestone(MID, meta={
            "capture_on": "departure" if cabin else "arrival",
            "arrival_iso": ARRIVAL, "departure_iso": DEPARTURE,
        })
        await get_ledger().insert_pledge_once({
            "_id": PID, "milestone_id": MID,
            "kind": "cabin_leg" if cabin else "mile",
            "status": "vaulted" if vault else "authorized",
            "payment_mode": "VAULT" if vault else "AUTHORIZE",
            "amount_eur": "20.00", "currency": "EUR",
            "authorization_id": "AUTH-B17", "vault_id": "VAULT-B17",
            "authorized_at": "2026-11-28T08:00:00+00:00",
            "authorization_expires_at": "2099-01-01T00:00:00+00:00",
        })
    asyncio.run(run())


def review(proposal):
    asyncio.run(get_ledger().set_proposal(MID, {
        "proposal": proposal, "at": simulated_now().isoformat(),
    }))


def approve(client, proposal):
    review(proposal)
    response = client.post(f"/api/escales/milestones/{MID}/captain-review/approve", headers=ADMIN)
    assert response.status_code == 200, response.text
    return response.json()


def settle(client, **kwargs):
    response = client.post("/api/escales/clock/settle", headers=ADMIN, json=kwargs)
    assert response.status_code == 200, response.text
    return response.json()["settled"]["actions"][0]["action"]


@pytest.mark.parametrize("vault", [False, True])
def test_approved_wait_never_unlocks_capture_then_fresh_capture_approval_does(api, monkeypatch, vault):
    client, fake = api
    if vault:
        fake = _VaultClockFake()
        set_paypal_client_factory(lambda: fake)
    seed(vault=vault)
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-13T08:00:00Z")
    approved = approve(client, "wait")
    assert approved["proposal"] == "wait"
    assert approved["at"] == "2026-11-13T08:00:00+00:00"
    monkeypatch.setenv("ESCALES_CLOCK_NOW", ARRIVAL)
    assert settle(client) == "await_review_approval"
    # A new, unapproved verdict must not reinterpret the earlier wait approval.
    review("capture")
    assert settle(client) == "await_review_approval"
    denied = client.post(f"/api/escales/pledges/{PID}/capture", headers=ADMIN)
    assert denied.status_code == 409
    assert "approved Captain capture review" in denied.json()["detail"]
    assert not fake.calls
    approve(client, "capture")
    assert settle(client) == "capture"
    entries = asyncio.run(get_ledger().list_finance())
    approvals = [e for e in entries if e["kind"] == "captain_review_approved"]
    assert [(e["proposal"], e["at"]) for e in approvals] == [
        ("wait", approved["at"]), ("capture", ARRIVAL),
    ]


@pytest.mark.parametrize("cabin", [False, True])
def test_direct_capture_requires_approval_at_arrival_or_cabin_departure(api, monkeypatch, cabin):
    client, fake = api
    seed(cabin=cabin)
    anchor = DEPARTURE if cabin else ARRIVAL
    monkeypatch.setenv("ESCALES_CLOCK_NOW", anchor)
    denied = client.post(f"/api/escales/pledges/{PID}/capture", headers=ADMIN)
    assert denied.status_code == 409
    assert "approved Captain capture review" in denied.json()["detail"]
    assert not fake.calls
    # A capture approved before the anchor is stale even after the anchor passes.
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-29T07:59:59Z" if not cabin else ARRIVAL)
    approve(client, "capture")
    assert settle(client, now=anchor) == "await_review_approval"
    denied = client.post(f"/api/escales/pledges/{PID}/capture", headers=ADMIN, json={"now": anchor})
    assert denied.status_code == 409
    assert not fake.calls
    monkeypatch.setenv("ESCALES_CLOCK_NOW", anchor)
    approve(client, "capture")
    captured = client.post(f"/api/escales/pledges/{PID}/capture", headers=ADMIN)
    assert captured.status_code == 200, captured.text
    assert captured.json()["status"] == "captured"
    assert any(call[0] == "capture" for call in fake.calls)


def test_cabin_settle_waits_for_fresh_departure_review(api, monkeypatch):
    client, fake = api
    seed(cabin=True)
    monkeypatch.setenv("ESCALES_CLOCK_NOW", ARRIVAL)
    approve(client, "capture")
    assert settle(client) == "wait"
    monkeypatch.setenv("ESCALES_CLOCK_NOW", DEPARTURE)
    assert settle(client) == "await_review_approval"
    assert not fake.calls
    approve(client, "capture")
    assert settle(client) == "capture"


def test_latest_approved_verdict_wins_and_clock_rewind_cannot_use_future_approval(api, monkeypatch):
    client, fake = api
    seed()
    monkeypatch.setenv("ESCALES_CLOCK_NOW", DEPARTURE)
    approve(client, "capture")
    assert asyncio.run(captain_review_approved(MID)) is True
    assert asyncio.run(captain_review_approved(MID, now=datetime.fromisoformat(ARRIVAL))) is False
    # Override is the effective clock, not the process's pinned clock.
    assert settle(client, now=ARRIVAL) == "await_review_approval"
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-12-02T08:00:01Z")
    approve(client, "wait")
    assert settle(client) == "await_review_approval"
    assert not fake.calls


@pytest.mark.parametrize("approval", [
    {},  # legacy milestone-only approval
    {"proposal": "capture", "at": "not-a-date"},
    {"proposal": "void", "at": ARRIVAL},
    {"proposal": "reauthorize", "at": ARRIVAL},
])
def test_legacy_or_invalid_approvals_fail_closed_and_are_preserved(api, monkeypatch, approval):
    client, fake = api
    seed()
    monkeypatch.setenv("ESCALES_CLOCK_NOW", DEPARTURE)
    entry = {"_id": "old-approval", "kind": "captain_review_approved", "milestone_id": MID, **approval}
    asyncio.run(get_ledger().append_finance(entry))
    assert settle(client) == "await_review_approval"
    assert asyncio.run(get_ledger().list_finance()) == [entry]
    assert not fake.calls


def test_cannot_approve_without_a_review(api):
    client, _ = api
    seed()
    response = client.post(f"/api/escales/milestones/{MID}/captain-review/approve", headers=ADMIN)
    assert response.status_code == 422
    assert "review is required" in response.json()["detail"]
    assert asyncio.run(get_ledger().list_finance()) == []


def test_review_stored_under_chat_alias_can_be_approved_for_canonical_milestone(api, monkeypatch):
    client, _ = api
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-12T08:00:00Z")
    asyncio.run(get_ledger().set_proposal("dep-mayotte", {
        "proposal": "capture", "at": simulated_now().isoformat(),
    }))
    response = client.post("/api/escales/milestones/dep-mayotte/captain-review/approve", headers=ADMIN)
    assert response.status_code == 200, response.text
    assert response.json()["milestone_id"] == "dep-dzaoudzi-mayotte"
    assert asyncio.run(captain_review_approved("dep-dzaoudzi-mayotte")) is True


def test_approving_a_pre_arrival_capture_report_after_arrival_requires_a_fresh_report(api, monkeypatch):
    client, fake = api
    seed()
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-13T08:00:00Z")
    review("capture")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", ARRIVAL)
    response = client.post(f"/api/escales/milestones/{MID}/captain-review/approve", headers=ADMIN)
    assert response.status_code == 200, response.text
    assert settle(client) == "await_review_approval"
    denied = client.post(f"/api/escales/pledges/{PID}/capture", headers=ADMIN)
    assert denied.status_code == 409
    assert not fake.calls
    approve(client, "capture")
    assert settle(client) == "capture"


@pytest.mark.parametrize("wait_at", [ARRIVAL, "2026-11-13T08:00:00Z"])
def test_latest_wait_approval_wins_even_with_a_pinned_or_rewound_clock(api, monkeypatch, wait_at):
    client, fake = api
    seed()
    monkeypatch.setenv("ESCALES_CLOCK_NOW", ARRIVAL)
    approve(client, "capture")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", wait_at)
    approve(client, "wait")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", ARRIVAL)
    assert settle(client) == "await_review_approval"
    assert not fake.calls
