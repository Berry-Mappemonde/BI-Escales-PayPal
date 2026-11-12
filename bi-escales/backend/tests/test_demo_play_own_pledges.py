"""Issue #145: in demo treasurer mode a visitor plays the treasurer on their own pledges only.

Ownership is proved with the pledge's ``client_key`` on every call. A pledge id alone, a
pledge from another browser, one made before the change or with the treasurer key: all
refused. The keyed treasurer routes behave exactly as before.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.milestones import captain_review_approved
from app.escales.pledges import get_ledger, reset_ledger
from app.escales.rate_limit import reset as reset_rate_limits
from app.routers.escales import router as escales_router, set_paypal_client_factory
from app.routers.escales_demo import router as demo_router
from tests.test_escales_router import FakePayPal

ADMIN = {"x-admin-key": "test-admin-key"}
MINE, THEIRS = "browser-a-key-0001", "browser-b-key-0002"
STOP = "dep-la-rochelle"
PLEDGE = {"amount_eur": "20.00", "description": "20 milles La Rochelle", "milestone_id": STOP}
ACTIONS = ("simulate-arrival", "approve", "capture", "void", "refund")
REFUSED = "this pledge was not made from this browser"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin-key")
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")
    monkeypatch.setenv("ESCALES_DEMO_TREASURER", "1")
    monkeypatch.setenv("ESCALES_DEMO_RATE_PER_MINUTE", "100")
    monkeypatch.delenv("ESCALES_ENV", raising=False)
    monkeypatch.delenv("ESCALES_CLOCK_NOW", raising=False)
    reset_ledger()
    reset_rate_limits()
    fake = FakePayPal()
    set_paypal_client_factory(lambda *_a, **_k: fake)
    app = FastAPI()
    app.include_router(escales_router)
    app.include_router(demo_router)
    with TestClient(app) as client:
        yield client, fake
    set_paypal_client_factory(None)
    reset_ledger()
    reset_rate_limits()


def _pledge(client, key=MINE, body=None, headers=None) -> dict:
    """Create and authorize a pledge the way a browser does: its own PayPal-Request-Id."""
    created = client.post("/api/escales/pledges", json=body or PLEDGE, headers={"PayPal-Request-Id": key, **(headers or {})})
    assert created.status_code == 200, created.text
    pledge_id = created.json()["id"]
    authorized = client.post(f"/api/escales/pledges/{pledge_id}/authorize")
    assert authorized.status_code == 200, authorized.text
    return authorized.json()


def _play(client, pledge_id, action, key=MINE):
    headers = {"X-Pledge-Key": key} if key is not None else {}
    return client.post(f"/api/escales/demo/pledges/{pledge_id}/{action}", headers=headers)


def _stored(pledge_id) -> dict:
    return asyncio.run(get_ledger().get_pledge(pledge_id))


def _money_calls(fake) -> list:
    return [call for call in fake.calls if call[0] not in ("create", "create_capture", "authorize", "orders.get", "authorizations.get")]


# --- The loop on one's own pledge -------------------------------------------------------


def test_own_pledge_goes_through_arrival_approval_and_capture(api):
    client, fake = api
    pledge = _pledge(client)
    assert pledge["status"] == "authorized"

    own = client.post("/api/escales/demo/pledges/own", json={"pledges": [{"id": pledge["id"], "key": MINE}]})
    assert own.status_code == 200, own.text
    assert own.json() == {"own": [{
        "pledge_id": pledge["id"], "status": "authorized",
        "arrival_simulated_at": None, "approved_at": None,
        "actions": ["simulate_arrival", "void"],
    }]}

    arrived = _play(client, pledge["id"], "simulate-arrival")
    assert arrived.status_code == 200, arrived.text
    assert arrived.json()["play"]["actions"] == ["approve", "void"]
    assert arrived.json()["play"]["arrival_simulated_at"]
    assert _money_calls(fake) == []

    approved = _play(client, pledge["id"], "approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["play"]["actions"] == ["capture", "void"]
    assert _money_calls(fake) == []

    captured = _play(client, pledge["id"], "capture")
    assert captured.status_code == 200, captured.text
    assert captured.json()["play"]["status"] == "captured"
    assert captured.json()["play"]["actions"] == ["refund"]
    assert captured.json()["pledge"]["status"] == "captured"
    assert _stored(pledge["id"])["status"] == "captured"
    assert _stored(pledge["id"])["capture_id"]
    # One real capture call, through the treasurer's capture path.
    assert [call[0] for call in _money_calls(fake)] == ["capture"]


def test_own_captured_pledge_can_be_refunded(api):
    client, fake = api
    pledge = _pledge(client)
    for action in ("simulate-arrival", "approve", "capture"):
        assert _play(client, pledge["id"], action).status_code == 200
    refunded = _play(client, pledge["id"], "refund")
    assert refunded.status_code == 200, refunded.text
    assert refunded.json()["play"]["status"] == "refunded"
    assert refunded.json()["play"]["actions"] == []
    assert _stored(pledge["id"])["status"] == "refunded"
    again = _play(client, pledge["id"], "refund")
    assert again.status_code == 409


def test_own_pledge_can_be_voided_instead(api):
    client, fake = api
    pledge = _pledge(client)
    voided = _play(client, pledge["id"], "void")
    assert voided.status_code == 200, voided.text
    assert voided.json()["play"]["status"] == "voided"
    assert voided.json()["play"]["actions"] == []
    assert _stored(pledge["id"])["status"] == "voided"
    assert "capture" not in [call[0] for call in _money_calls(fake)]
    # Nothing left to play.
    assert _play(client, pledge["id"], "capture").status_code == 409


def test_the_steps_cannot_be_skipped(api):
    client, fake = api
    pledge = _pledge(client)
    assert _play(client, pledge["id"], "approve").status_code == 409
    assert _play(client, pledge["id"], "capture").status_code == 409
    assert _play(client, pledge["id"], "simulate-arrival").status_code == 200
    capture = _play(client, pledge["id"], "capture")
    assert capture.status_code == 409
    assert "approve" in capture.json()["detail"]
    assert _stored(pledge["id"])["status"] == "authorized"
    assert _money_calls(fake) == []


def test_repeating_a_step_changes_nothing(api):
    client, _fake = api
    pledge = _pledge(client)
    first = _play(client, pledge["id"], "simulate-arrival").json()["play"]
    second = _play(client, pledge["id"], "simulate-arrival").json()["play"]
    assert second == first
    once = _play(client, pledge["id"], "approve").json()["play"]
    twice = _play(client, pledge["id"], "approve").json()["play"]
    assert twice == once


# --- Ownership: never a pledge id alone -------------------------------------------------


@pytest.mark.parametrize("action", ACTIONS)
def test_another_browsers_pledge_is_refused(api, action):
    client, fake = api
    theirs = _pledge(client, key=THEIRS)
    refused = _play(client, theirs["id"], action, key=MINE)
    assert refused.status_code == 403
    assert refused.json()["detail"] == REFUSED
    assert _stored(theirs["id"])["status"] == "authorized"
    assert "demo_play" not in _stored(theirs["id"])
    assert _money_calls(fake) == []


@pytest.mark.parametrize("action", ACTIONS)
def test_a_pledge_id_alone_is_refused(api, action):
    client, fake = api
    pledge = _pledge(client)
    for key in (None, "", "   "):
        refused = _play(client, pledge["id"], action, key=key)
        assert refused.status_code == 403
        assert refused.json()["detail"] == REFUSED
    assert _money_calls(fake) == []
    assert _stored(pledge["id"])["status"] == "authorized"


def test_an_unknown_pledge_id_gets_the_same_refusal(api):
    client, _fake = api
    refused = _play(client, "no-such-pledge", "capture")
    assert refused.status_code == 403
    assert refused.json()["detail"] == REFUSED


def test_a_captured_pledge_of_another_browser_cannot_be_refunded(api):
    client, fake = api
    theirs = _pledge(client, key=THEIRS)
    for action in ("simulate-arrival", "approve", "capture"):
        assert _play(client, theirs["id"], action, key=THEIRS).status_code == 200
    assert _play(client, theirs["id"], "refund", key=MINE).status_code == 403
    assert _stored(theirs["id"])["status"] == "captured"


def test_a_pledge_made_before_the_change_stays_view_only(api, monkeypatch):
    client, fake = api
    # Made while demo mode was off: it has a client key but was never marked playable.
    monkeypatch.delenv("ESCALES_DEMO_TREASURER")
    old = _pledge(client)
    assert "demo_playable" not in _stored(old["id"])
    monkeypatch.setenv("ESCALES_DEMO_TREASURER", "1")
    for action in ACTIONS:
        assert _play(client, old["id"], action).status_code == 403
    own = client.post("/api/escales/demo/pledges/own", json={"pledges": [{"id": old["id"], "key": MINE}]})
    assert own.json() == {"own": []}
    assert _money_calls(fake) == []


def test_a_pledge_made_with_the_treasurer_key_stays_view_only(api):
    client, _fake = api
    keyed = _pledge(client, headers=ADMIN)
    assert "demo_playable" not in _stored(keyed["id"])
    assert _play(client, keyed["id"], "void").status_code == 403


def test_a_pledge_made_without_a_request_id_is_not_playable(api):
    client, _fake = api
    created = client.post("/api/escales/pledges", json=PLEDGE)
    assert created.status_code == 200, created.text
    assert "demo_playable" not in _stored(created.json()["id"])


def test_the_own_list_leaves_out_what_is_not_proved_and_says_nothing_else(api):
    client, _fake = api
    mine = _pledge(client)
    theirs = _pledge(client, key=THEIRS)
    own = client.post("/api/escales/demo/pledges/own", json={"pledges": [
        {"id": mine["id"], "key": MINE},
        {"id": theirs["id"], "key": MINE},
        {"id": "no-such-pledge", "key": MINE},
    ]})
    assert [row["pledge_id"] for row in own.json()["own"]] == [mine["id"]]
    too_many = client.post("/api/escales/demo/pledges/own", json={"pledges": [{"id": f"p{i}", "key": "k"} for i in range(51)]})
    assert too_many.status_code == 422


def test_no_demo_answer_ever_carries_a_pledge_key(api):
    client, _fake = api
    pledge = _pledge(client)
    texts = [client.post("/api/escales/demo/pledges/own", json={"pledges": [{"id": pledge["id"], "key": MINE}]}).text]
    for action in ("simulate-arrival", "approve", "capture", "refund"):
        texts.append(_play(client, pledge["id"], action).text)
    texts.append(client.get("/api/escales/pledges").text)
    texts.append(client.get(f"/api/escales/pledges/{pledge['id']}").text)
    for text in texts:
        assert MINE not in text
        assert "client_key" not in text


# --- Scope: nothing shared moves ---------------------------------------------------------


def test_simulated_arrival_touches_only_that_pledge(api):
    client, fake = api
    mine = _pledge(client)
    other = _pledge(client, key=THEIRS)
    clock_before = client.get("/api/escales/clock").json()
    milestones_before = client.get("/api/escales/milestones").json()

    assert _play(client, mine["id"], "simulate-arrival").status_code == 200
    assert _play(client, mine["id"], "approve").status_code == 200

    # The shared clock and the stop itself have not moved.
    assert client.get("/api/escales/clock").json() == clock_before
    assert client.get("/api/escales/milestones").json() == milestones_before
    assert asyncio.run(captain_review_approved(STOP)) is False
    # The other pledge on the same stop knows nothing of it.
    assert "demo_play" not in _stored(other["id"])
    assert _play(client, other["id"], "capture", key=THEIRS).status_code == 409
    # And the treasurer, with the key, still cannot capture it before the real arrival.
    keyed = client.post(f"/api/escales/pledges/{other['id']}/capture", headers=ADMIN)
    assert keyed.status_code in (409, 422)
    assert _stored(other["id"])["status"] == "authorized"
    assert _money_calls(fake) == []


def test_my_demo_approval_does_not_let_the_keyed_route_capture_early(api):
    client, fake = api
    mine = _pledge(client)
    for action in ("simulate-arrival", "approve"):
        assert _play(client, mine["id"], action).status_code == 200
    keyed = client.post(f"/api/escales/pledges/{mine['id']}/capture", headers=ADMIN)
    assert keyed.status_code in (409, 422)
    assert _stored(mine["id"])["status"] == "authorized"
    assert _money_calls(fake) == []


# --- The keyed treasurer routes are unaffected -------------------------------------------


@pytest.mark.parametrize("action", ["capture", "void", "refund"])
def test_keyed_money_routes_still_need_the_key_in_demo_mode(api, action):
    client, fake = api
    pledge = _pledge(client)
    no_key = client.post(f"/api/escales/pledges/{pledge['id']}/{action}", json={})
    assert no_key.status_code == 401
    # The pledge key is not a treasurer key.
    with_pledge_key = client.post(f"/api/escales/pledges/{pledge['id']}/{action}", json={}, headers={"X-Pledge-Key": MINE})
    assert with_pledge_key.status_code == 401
    assert _stored(pledge["id"])["status"] == "authorized"
    assert _money_calls(fake) == []


def test_keyed_void_and_review_approval_work_as_before(api):
    client, _fake = api
    pledge = _pledge(client)
    assert client.post(f"/api/escales/milestones/{STOP}/captain-review/approve").status_code == 401
    voided = client.post(f"/api/escales/pledges/{pledge['id']}/void", headers=ADMIN)
    assert voided.status_code == 200, voided.text
    assert voided.json()["status"] == "voided"


def test_the_stop_wide_judge_moment_routes_still_need_the_key(api):
    client, _fake = api
    for action in ("simulate-arrival", "cancel", "reset"):
        assert client.post(f"/api/escales/demo/stops/{STOP}/{action}").status_code == 401
        assert client.post(f"/api/escales/demo/stops/{STOP}/{action}", headers={"X-Pledge-Key": MINE}).status_code == 401


# --- Only in sandbox demo mode, and rate-limited ------------------------------------------


@pytest.mark.parametrize(
    "env",
    [
        {"ESCALES_DEMO_TREASURER": ""},
        {"PAYPAL_ENV": "live"},
        {"ESCALES_ENV": "production"},
    ],
)
def test_demo_routes_are_closed_outside_sandbox_demo_mode(api, monkeypatch, env):
    client, fake = api
    pledge = _pledge(client)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    for action in ACTIONS:
        assert _play(client, pledge["id"], action).status_code == 403
    assert client.post("/api/escales/demo/pledges/own", json={"pledges": []}).status_code == 403
    assert _money_calls(fake) == []
    assert _stored(pledge["id"])["status"] == "authorized"


def test_demo_actions_are_rate_limited_per_ip(api, monkeypatch):
    client, _fake = api
    monkeypatch.setenv("ESCALES_DEMO_RATE_PER_MINUTE", "3")
    pledge = _pledge(client)
    codes = [_play(client, pledge["id"], "simulate-arrival").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    limited = _play(client, pledge["id"], "simulate-arrival")
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1


def test_wrong_keys_are_throttled_too(api, monkeypatch):
    client, _fake = api
    monkeypatch.setenv("ESCALES_DEMO_RATE_PER_MINUTE", "3")
    pledge = _pledge(client)
    codes = [_play(client, pledge["id"], "void", key=f"guess-{n}").status_code for n in range(5)]
    assert codes == [403, 403, 403, 429, 429]
    assert _stored(pledge["id"])["status"] == "authorized"


def test_pending_demo_payment_can_refresh_without_replaying_capture(api, monkeypatch):
    client, fake = api
    pledge = _pledge(client)
    for action in ("simulate-arrival", "approve", "capture"):
        assert _play(client, pledge["id"], action).status_code == 200
    async def make_pending():
        row = await get_ledger().get_pledge(pledge["id"])
        row["status"] = "pending"
        row.pop("demo_play", None)
        await get_ledger().save_pledge(row)
    asyncio.run(make_pending())
    monkeypatch.setattr(fake, "get_capture", lambda capture_id: {"id": capture_id, "status": "COMPLETED"}, raising=False)
    before = list(_money_calls(fake))
    response = _play(client, pledge["id"], "capture")
    assert response.status_code == 200, response.text
    assert response.json()["pledge"]["status"] == "captured"
    assert _money_calls(fake) == before
