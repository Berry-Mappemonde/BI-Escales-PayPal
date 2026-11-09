"""Task V-2: cabin pledges use VAULT when leg departure is >29 days away (mock PayPal only)."""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales import captain
from app.escales.config import AUTH_MAX_DAYS
from app.escales.departure_clock import refuse_early_capture, run_departure_clock
from app.escales.ledger import get_ledger, reset_ledger
from app.escales.milestones import record_evidence
from app.escales.naviguide_bridge import clock_legs, leg_by_id, sync_leg_shells
from app.escales.pledges import (
    authorize_pledge,
    capture_pledge,
    create_pledge,
    register_vault_pledge,
)
from app.routers.escales import router, set_paypal_client_factory
from tests.review_helpers import approve_capture_review
from tests.test_escales_pledges import Spy, _names


NEAR_LEG = "leg-la-rochelle-to-ajaccio-corse"


class VaultSpy(Spy):
    def create_payment_token(self, setup_token_id, **kwargs):
        self.calls.append(("payment_token", setup_token_id))
        return {"id": f"VAULT-{setup_token_id}"}

    def get_setup_token(self, setup_token_id):
        self.calls.append(("get_setup_token", setup_token_id))
        return {"status": "APPROVED", "id": setup_token_id}

    def charge_vaulted(self, vault_id, amount_eur, reference_id, source="paypal", **kwargs):
        self.calls.append(("charge_vaulted", vault_id, amount_eur, reference_id, source))
        return {"id": "CAP-V", "status": "COMPLETED"}

    def delete_payment_token(self, vault_id):
        self.calls.append(("delete_token", vault_id))
        return {}


@pytest.fixture(autouse=True)
def memory(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_VAULT_ENABLED", "1")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-19T08:00:00Z")
    reset_ledger()
    yield
    reset_ledger()


def _leg_departure(leg_id: str = NEAR_LEG) -> dt.datetime:
    leg = leg_by_id(leg_id)
    assert leg is not None
    return dt.datetime.fromisoformat(leg["departure_iso"].replace("Z", "+00:00"))


def _mode_get(leg_id: str) -> str:
    app = FastAPI()
    app.include_router(router)
    ledger = get_ledger()
    with patch.object(ledger, "ensure_milestone", side_effect=AssertionError("GET must not write")):
        response = TestClient(app).get(
            "/api/escales/pledges/mode",
            params={"milestone_id": leg_id, "kind": "cabin_leg"},
        )
    assert response.status_code == 200
    return response.json()["payment_mode"]


@pytest.mark.parametrize("days_before,expected", [(28, "AUTHORIZE"), (29, "AUTHORIZE"), (30, "VAULT")])
def test_cabin_mode_preview_matches_create_pledge(days_before, expected, monkeypatch):
    async def body():
        await sync_leg_shells()
        departure = _leg_departure()
        monkeypatch.setenv(
            "ESCALES_CLOCK_NOW",
            (departure - dt.timedelta(days=days_before)).replace(microsecond=0).isoformat(),
        )
        assert _mode_get(NEAR_LEG) == expected
        spy = VaultSpy()
        created = await create_pledge(
            amount_eur="80.00",
            description="cabine V-2",
            milestone_id=NEAR_LEG,
            client=spy,
            kind="cabin_leg",
            client_key=f"v2-mode-{days_before}",
        )
        assert created["payment_mode"] == expected
        if expected == "VAULT":
            assert _names(spy) == ["setup_token"]
            assert "create" not in _names(spy)
        else:
            assert _names(spy) == ["create"]

    asyncio.run(body())


def test_cabin_vault_disabled_refuses_far_departure(monkeypatch):
    monkeypatch.setenv("ESCALES_VAULT_ENABLED", "0")

    async def body():
        await sync_leg_shells()
        departure = _leg_departure()
        monkeypatch.setenv(
            "ESCALES_CLOCK_NOW",
            (departure - dt.timedelta(days=AUTH_MAX_DAYS + 1)).isoformat(),
        )
        app = FastAPI()
        app.include_router(router)
        response = TestClient(app).get(
            "/api/escales/pledges/mode",
            params={"milestone_id": NEAR_LEG, "kind": "cabin_leg"},
        )
        assert response.status_code == 422
        with pytest.raises(ValueError, match="29 days"):
            await create_pledge(
                amount_eur="80.00",
                description="cabine refusée",
                milestone_id=NEAR_LEG,
                client=VaultSpy(),
                kind="cabin_leg",
                client_key="v2-vault-off",
            )

    asyncio.run(body())


def test_cancelled_leg_refuses_new_cabin(monkeypatch):
    async def body():
        await sync_leg_shells()
        departure = _leg_departure()
        monkeypatch.setenv(
            "ESCALES_CLOCK_NOW",
            (departure - dt.timedelta(days=20)).isoformat(),
        )
        spy = VaultSpy()
        await record_evidence(NEAR_LEG, met=False, facts={"cancelled": True})
        with pytest.raises(ValueError, match="cancelled"):
            await create_pledge(
                amount_eur="80.00",
                description="cabine annulée",
                milestone_id=NEAR_LEG,
                client=spy,
                kind="cabin_leg",
                client_key="v2-cancel",
            )
        assert spy.calls == []

    asyncio.run(body())


def test_vaulted_cabin_charges_at_departure_not_before(monkeypatch):
    async def body():
        await sync_leg_shells()
        departure = _leg_departure()
        monkeypatch.setenv(
            "ESCALES_CLOCK_NOW",
            (departure - dt.timedelta(days=40)).isoformat(),
        )
        spy = VaultSpy()
        created = await create_pledge(
            amount_eur="80.00",
            description="cabine vault",
            milestone_id=NEAR_LEG,
            client=spy,
            kind="cabin_leg",
            client_key="v2-vault-cap",
        )
        assert created["payment_mode"] == "VAULT"
        vaulted = await register_vault_pledge(created["_id"], spy)
        assert vaulted["status"] == "vaulted"
        assert vaulted.get("vault_id")
        with pytest.raises(ValueError, match="leg departure"):
            await refuse_early_capture(vaulted, now=departure - dt.timedelta(hours=1))
        monkeypatch.setenv("ESCALES_CLOCK_NOW", departure.isoformat())
        await approve_capture_review(NEAR_LEG)
        settled = await run_departure_clock(spy, now=departure)
        actions = {row["pledge_id"]: row["action"] for row in settled["actions"]}
        assert actions.get(created["_id"]) == "capture"
        assert ("charge_vaulted", vaulted["vault_id"], "80.00", created["_id"], "paypal") in spy.calls
        stored = await get_ledger().get_pledge(created["_id"])
        assert stored["status"] == "captured"

    asyncio.run(body())


def test_near_cabin_authorize_no_vault_path(monkeypatch):
    async def body():
        await sync_leg_shells()
        departure = _leg_departure()
        monkeypatch.setenv(
            "ESCALES_CLOCK_NOW",
            (departure - dt.timedelta(days=AUTH_MAX_DAYS)).isoformat(),
        )
        spy = VaultSpy()
        created = await create_pledge(
            amount_eur="80.00",
            description="cabine proche",
            milestone_id=NEAR_LEG,
            client=spy,
            kind="cabin_leg",
            client_key="v2-near",
        )
        assert created["payment_mode"] == "AUTHORIZE"
        authorized = await authorize_pledge(created["_id"], spy)
        assert authorized["status"] == "authorized"
        assert "setup_token" not in _names(spy)
        assert "authorize" in _names(spy)

    asyncio.run(body())


def test_cabin_auth_expiring_before_departure_surfaces_in_review(monkeypatch):
    """Gap follow-up: no dedicated reauth flag yet; treasurer sees expiry metadata."""

    async def body():
        await sync_leg_shells()
        departure = _leg_departure()
        monkeypatch.setenv(
            "ESCALES_CLOCK_NOW",
            (departure - dt.timedelta(days=AUTH_MAX_DAYS)).isoformat(),
        )
        spy = VaultSpy()
        created = await create_pledge(
            amount_eur="80.00",
            description="cabine auth horizon",
            milestone_id=NEAR_LEG,
            client=spy,
            kind="cabin_leg",
            client_key="v2-expiry",
        )
        authorized = await authorize_pledge(created["_id"], spy)
        # Simulate departure slipping after PayPal's 29-day authorization window.
        authorized["authorization_expires_at"] = (departure - dt.timedelta(days=10)).isoformat()
        authorized["authorized_at"] = (
            dt.datetime.fromisoformat(authorized["authorization_expires_at"].replace("Z", "+00:00"))
            - dt.timedelta(days=AUTH_MAX_DAYS)
        ).isoformat()
        await get_ledger().save_pledge(authorized)
        monkeypatch.setenv("ESCALES_CLOCK_NOW", departure.isoformat())
        await record_evidence(NEAR_LEG, met=True, facts={"departed": True})
        review = await captain.review(NEAR_LEG)
        pending = review["pending_authorizations"]
        row = next(item for item in pending if item["pledge_id"] == created["_id"])
        assert row["authorization_expires_at"] == authorized["authorization_expires_at"]
        assert row["authorization_age_days"] is not None
        assert row["authorization_age_days"] >= AUTH_MAX_DAYS
        await approve_capture_review(NEAR_LEG)
        with pytest.raises(ValueError, match="expired"):
            await capture_pledge(created["_id"], spy, effective_at=departure)
        assert all(call[0] != "capture" for call in spy.calls)

    asyncio.run(body())


def test_first_clock_leg_departure_anchors_vault_threshold(monkeypatch):
    """Sanity: clock_legs[0] departure anchor matches refuse_early_authorization."""
    leg = clock_legs()[0]
    departure = dt.datetime.fromisoformat(leg["departure_iso"].replace("Z", "+00:00"))
    for days, mode in ((28, "AUTHORIZE"), (30, "VAULT")):
        monkeypatch.setenv(
            "ESCALES_CLOCK_NOW",
            (departure - dt.timedelta(days=days)).replace(microsecond=0).isoformat(),
        )
        assert _mode_get(leg["id"]) == mode
