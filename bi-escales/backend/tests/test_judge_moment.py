"""Judge-moment demo routes (sandbox, treasurer key, La Rochelle only)."""
from __future__ import annotations

import asyncio
import copy
import datetime as dt
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.departure_clock import _parse_moment
from app.escales.naviguide_bridge import local_schedule_export, resolve_schedule_milestone
from app.escales.pledges import authorize_pledge, create_pledge, get_ledger, reset_ledger
from app.escales.rate_limit import reset as reset_rate_limits
from app.routers.escales import router as escales_router, set_paypal_client_factory
from app.routers.escales_demo import router as demo_router


class FakePayPal:
    def create_authorize_order(self, amount_eur, description, reference_id, **kwargs):
        return {
            "id": f"ORD-{reference_id[:8]}",
            "status": "CREATED",
            "links": [{"rel": "approve", "href": "https://example.test/approve"}],
        }

    def authorize_order(self, order_id, **kwargs):
        return {
            "id": order_id,
            "status": "COMPLETED",
            "purchase_units": [{
                "payments": {"authorizations": [{"id": f"AUTH-{order_id}", "expiration_time": "2099-01-01T00:00:00Z"}]},
            }],
        }

    def capture_authorization(self, authorization_id, **kwargs):
        return {"id": f"CAP-{authorization_id[-6:]}", "status": "COMPLETED"}

    def void_authorization(self, authorization_id, **kwargs):
        return {"id": f"VOID-{authorization_id[-6:]}"}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "judge-moment-key")
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")
    monkeypatch.setenv("ESCALES_DEMO_TREASURER", "true")
    monkeypatch.setenv("ESCALES_DEMO_RATE_PER_MINUTE", "5")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2027-06-01T08:00:00+00:00")
    monkeypatch.delenv("ESCALES_ENV", raising=False)

    async def noop(_pledge, **kwargs):
        return None

    monkeypatch.setattr("app.escales.departure_clock.refuse_early_authorization", noop)
    reset_ledger()
    reset_rate_limits()
    set_paypal_client_factory(lambda: FakePayPal())
    yield
    reset_ledger()
    reset_rate_limits()
    set_paypal_client_factory(None)


@pytest.fixture
def api():
    app = FastAPI()
    app.include_router(escales_router)
    app.include_router(demo_router)
    return TestClient(app, headers=KEY)


@pytest.fixture
def anon():
    app = FastAPI()
    app.include_router(escales_router)
    app.include_router(demo_router)
    return TestClient(app)


KEY = {"x-admin-key": "judge-moment-key"}


def _path(action: str, milestone_id: str = "dep-la-rochelle") -> str:
    return f"/api/escales/demo/stops/{milestone_id}/{action}"


async def _seed_authorized(milestone_id: str = "dep-la-rochelle") -> str:
    fake = FakePayPal()
    created = await create_pledge(
        amount_eur="15.00",
        description="miles demo",
        milestone_id=milestone_id,
        client=fake,
        kind="mile",
    )
    saved = await authorize_pledge(created["_id"], fake)
    return saved["_id"]


def test_demo_routes_refused_when_flag_off(api, monkeypatch):
    monkeypatch.delenv("ESCALES_DEMO_TREASURER", raising=False)
    assert api.post(_path("simulate-arrival")).status_code == 403


def test_demo_routes_refused_when_paypal_live(api, monkeypatch):
    monkeypatch.setenv("PAYPAL_ENV", "production")
    assert api.post(_path("simulate-arrival")).status_code == 403


def test_demo_routes_refused_when_escales_production(api, monkeypatch):
    monkeypatch.setenv("ESCALES_ENV", "production")
    assert api.post(_path("simulate-arrival")).status_code == 403


def test_non_allowlisted_milestone_returns_404(api):
    assert api.post(_path("cancel", "dep-dzaoudzi-mayotte")).status_code == 404


def test_demo_rate_limit_returns_429(api, monkeypatch):
    monkeypatch.setenv("ESCALES_DEMO_RATE_PER_MINUTE", "2")
    reset_rate_limits()
    assert api.post(_path("reset")).status_code == 200
    assert api.post(_path("reset")).status_code == 200
    blocked = api.post(_path("reset"))
    assert blocked.status_code == 429
    assert blocked.headers.get("retry-after")


def test_simulate_arrival_captures_la_rochelle_only(api, monkeypatch):
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-12T08:00:00+00:00")

    async def run():
        la = await _seed_authorized("dep-la-rochelle")
        other = await _seed_authorized("dep-dzaoudzi-mayotte")
        doc = await resolve_schedule_milestone("dep-la-rochelle", read_only=True)
        arrival = _parse_moment(str((doc or {}).get("meta", {}).get("arrival_iso")))
        assert arrival is not None
        res = api.post(_path("simulate-arrival"))
        assert res.status_code == 200
        body = res.json()
        assert body["milestone_id"] == "dep-la-rochelle"
        captures = [row for row in body["actions"] if row.get("action") == "capture"]
        assert len(captures) == 1
        assert captures[0]["pledge_id"] == la
        assert captures[0].get("capture_id")
        la_row = await get_ledger().get_pledge(la)
        other_row = await get_ledger().get_pledge(other)
        assert la_row["status"] == "captured"
        assert other_row["status"] == "authorized"

    asyncio.run(run())


def test_cancel_voids_la_rochelle_and_skips_captured(api):
    async def run():
        pledge_id = await _seed_authorized()
        authorized_id = await _seed_authorized()
        ledger = get_ledger()
        doc = await ledger.get_pledge(pledge_id)
        doc["status"] = "captured"
        doc["capture_id"] = "CAP-ALREADY"
        await ledger.save_pledge(doc)
        await _seed_authorized("dep-dzaoudzi-mayotte")
        res = api.post(_path("cancel"))
        assert res.status_code == 200
        body = res.json()
        voids = [row for row in body["actions"] if row.get("action") == "void"]
        assert len(voids) == 1
        assert voids[0]["pledge_id"] == authorized_id
        assert voids[0].get("void_id")
        captured = await ledger.get_pledge(pledge_id)
        assert captured["status"] == "captured"
        assert captured["capture_id"] == "CAP-ALREADY"
        other = await ledger.get_pledge(
            [p["_id"] for p in await ledger.list_pledges() if p["milestone_id"] == "dep-dzaoudzi-mayotte"][0]
        )
        assert other["status"] == "authorized"

    asyncio.run(run())


def test_cancel_all_captured_returns_empty_actions(api):
    async def run():
        pledge_id = await _seed_authorized()
        ledger = get_ledger()
        doc = await ledger.get_pledge(pledge_id)
        doc["status"] = "captured"
        doc["capture_id"] = "CAP-ONLY"
        await ledger.save_pledge(doc)
        body = api.post(_path("cancel")).json()
        assert body["actions"] == []

    asyncio.run(run())


def test_cancel_does_not_touch_naviguide_export(api, monkeypatch):
    export_before = copy.deepcopy(local_schedule_export())
    naviguide_calls: list[str] = []

    async def spy_sync(*args, **kwargs):
        naviguide_calls.append("sync")
        return []

    monkeypatch.setattr("app.escales.naviguide_bridge.sync_milestone_shells", spy_sync)
    monkeypatch.setattr("app.escales.naviguide_bridge.sync_leg_shells", spy_sync)

    async def run():
        await _seed_authorized()
        assert api.post(_path("cancel")).status_code == 200

    asyncio.run(run())
    export_after = local_schedule_export()
    assert json.dumps(export_before, sort_keys=True) == json.dumps(export_after, sort_keys=True)
    assert naviguide_calls == []


def test_reset_leaves_captured_pledge_after_simulate(api):
    async def run():
        pledge_id = await _seed_authorized()
        assert api.post(_path("simulate-arrival")).status_code == 200
        captured = await get_ledger().get_pledge(pledge_id)
        assert captured["status"] == "captured"
        assert api.post(_path("reset")).status_code == 200
        still = await get_ledger().get_pledge(pledge_id)
        assert still["status"] == "captured"
        assert still.get("capture_id")

    asyncio.run(run())


def test_reset_clears_demo_override_and_keeps_captured(api):
    async def run():
        pledge_id = await _seed_authorized()
        api.post(_path("cancel"))
        ledger = get_ledger()
        stored = await ledger.get_milestone("dep-la-rochelle")
        assert (stored.get("meta") or {}).get("demo_cancelled") is True
        reset = api.post(_path("reset"))
        assert reset.status_code == 200
        stored = await ledger.get_milestone("dep-la-rochelle")
        assert "demo_cancelled" not in (stored.get("meta") or {})
        row = await ledger.get_pledge(pledge_id)
        assert row["status"] == "voided"

    asyncio.run(run())


def test_keyed_routes_still_require_admin_key(anon):
    assert anon.post("/api/escales/clock/settle", json={}).status_code == 401
    pledge_id = asyncio.run(_seed_authorized())
    assert anon.post(f"/api/escales/pledges/{pledge_id}/capture", json={}).status_code == 401
    assert anon.post(f"/api/escales/pledges/{pledge_id}/void", json={}).status_code == 401
    assert anon.post("/api/escales/milestones/dep-la-rochelle/captain-review/approve").status_code == 401


@pytest.mark.parametrize("action", ["simulate-arrival", "cancel", "reset"])
def test_demo_routes_require_treasurer_key(anon, action):
    """HamidZ11 #149 blocker 1: no anonymous capture / void / stop-wide flag."""
    async def run():
        pledge_id = await _seed_authorized()
        assert anon.post(_path(action)).status_code == 401
        assert anon.post(_path(action), headers={"x-admin-key": "wrong"}).status_code == 403
        row = await get_ledger().get_pledge(pledge_id)
        assert row["status"] == "authorized"
        stored = await get_ledger().get_milestone("dep-la-rochelle")
        assert not ((stored or {}).get("meta") or {}).get("demo_cancelled")

    asyncio.run(run())


def test_simulate_arrival_leaves_no_persisted_approval(api, monkeypatch):
    """HamidZ11 #149 blocker 2: the real clock must not inherit a demo approval."""
    from app.escales.departure_clock import run_departure_clock_for_milestone
    from app.escales.ledger import list_finance_entries
    from app.escales.milestones import captain_review_approved

    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-12T08:00:00+00:00")

    async def run():
        ledger = get_ledger()
        before = await ledger.get_milestone("dep-la-rochelle")
        before_proposal = copy.deepcopy((before or {}).get("proposal"))
        await _seed_authorized()
        res = api.post(_path("simulate-arrival"))
        assert res.status_code == 200
        assert res.json()["approval_persisted"] is False
        kinds = [row.get("kind") for row in await list_finance_entries()]
        assert "captain_review_approved" not in kinds
        after = await ledger.get_milestone("dep-la-rochelle")
        assert (after or {}).get("proposal") == before_proposal
        doc = await resolve_schedule_milestone("dep-la-rochelle", read_only=True)
        arrival = _parse_moment(str((doc or {}).get("meta", {}).get("arrival_iso")))
        late = arrival + dt.timedelta(days=1)
        assert await captain_review_approved("dep-la-rochelle", now=late) is False
        fresh = await _seed_authorized()
        settled = await run_departure_clock_for_milestone(FakePayPal(), "dep-la-rochelle", now=late)
        rows = [r for r in settled["actions"] if r.get("pledge_id") == fresh]
        assert rows and rows[0]["action"] == "await_review_approval"
        assert (await ledger.get_pledge(fresh))["status"] == "authorized"

    asyncio.run(run())
