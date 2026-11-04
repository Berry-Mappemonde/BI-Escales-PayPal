"""HTTP contract for /api/escales. PayPal is a fake. No network."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.audit import AUDIT_COLLECTION, list_entries
from app.escales.pledges import reset_ledger
from app.escales.config import cors_origins, paypal_webhook_url
from app.routers.escales import _public_pledge, router, set_paypal_client_factory

PLEDGE = {
    "amount_eur": "20.00",
    "description": "20 milles Mayotte",
    "milestone_id": "dep-mayotte",
}
ADMIN = {"x-admin-key": "test-admin-key"}


class FakePayPal:
    def __init__(self):
        self.calls = []
        self.n = 0
        self.order_status = "APPROVED"

    def create_authorize_order(self, amount_eur, description, reference_id, idempotency_key=None):
        self.calls.append(("create", amount_eur, idempotency_key))
        self.n += 1
        order_id = f"ORDER{self.n}"
        return {
            "id": order_id,
            "status": "CREATED",
            "intent": "AUTHORIZE",
            "links": [{
                "rel": "approve",
                "href": f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}",
            }],
        }

    def authorize_order(self, order_id):
        self.calls.append(("authorize", order_id))
        return {
            "id": order_id,
            "purchase_units": [{
                "payments": {
                    "authorizations": [{
                        "id": f"AUTH-{order_id}",
                        "expiration_time": "2026-12-01T00:00:00Z",
                    }],
                },
            }],
        }

    def capture_authorization(self, authorization_id, final=True):
        self.calls.append(("capture", authorization_id))
        return {"id": "CAP", "status": "COMPLETED"}

    def void_authorization(self, authorization_id):
        self.calls.append(("void", authorization_id))
        return {}

    def get_order(self, order_id):
        self.calls.append(("orders.get", order_id))
        return {"id": order_id, "status": self.order_status}

    def get_authorization(self, authorization_id):
        self.calls.append(("authorizations.get", authorization_id))
        return {"id": authorization_id, "status": "CREATED"}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin-key")
    monkeypatch.delenv("ESCALES_TOOLKIT_ENABLED", raising=False)
    monkeypatch.delenv("ESCALES_LLM_ENABLED", raising=False)
    monkeypatch.delenv("ESCALES_ENV", raising=False)
    monkeypatch.delenv("ESCALES_RATE_LIMIT_ENABLED", raising=False)
    reset_ledger()
    fake = FakePayPal()
    set_paypal_client_factory(lambda: fake)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client, fake
    set_paypal_client_factory(None)
    reset_ledger()


def _create(client, key, body=None):
    return client.post(
        "/api/escales/pledges",
        json=body or PLEDGE,
        headers={"PayPal-Request-Id": key},
    )


def _authorize(client, pledge_id):
    return client.post(f"/api/escales/pledges/{pledge_id}/authorize")


def _ready(client, key, body=None):
    created = _create(client, key, body)
    assert created.status_code == 200, created.text
    pledge_id = created.json()["id"]
    authorized = _authorize(client, pledge_id)
    assert authorized.status_code == 200, authorized.text
    return created.json(), authorized.json()


def test_create_pledge_returns_order_and_approve_link(api):
    client, fake = api
    response = _create(client, "create-1")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "created"
    assert body["intent"] == "AUTHORIZE"
    assert body["currency"] == "EUR"
    assert body["amount_eur"] == "20.00"
    assert body["order_id"] == "ORDER1"
    assert body["approve_link"] == "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1"
    bare = _public_pledge({"_id": "old", "order_id": "ORDER9", "kind": "mile", "milestone_id": "dep-mayotte"})
    assert bare["approve_link"] == "https://www.sandbox.paypal.com/checkoutnow?token=ORDER9"
    assert "client_key" not in body
    assert fake.calls[0] == ("create", "20.00", "create-1")


def test_same_paypal_request_id_is_idempotent(api):
    client, fake = api
    first = _create(client, "same-key").json()
    second = _create(client, "same-key", {**PLEDGE, "amount_eur": "60.00"}).json()
    assert first["id"] == second["id"]
    assert first["order_id"] == second["order_id"]
    assert [call[0] for call in fake.calls] == ["create"]


def test_authorize_stores_id_and_expiration(api):
    client, _fake = api
    created, authorized = _ready(client, "auth-1")
    assert authorized["status"] == "authorized"
    assert authorized["authorization_id"] == "AUTH-ORDER1"
    assert authorized["authorization_expires_at"] == "2026-12-01T00:00:00Z"
    fetched = client.get(f"/api/escales/pledges/{created['id']}", headers=ADMIN)
    assert fetched.status_code == 200
    assert fetched.json()["authorization_id"] == "AUTH-ORDER1"
    assert fetched.json()["status"] == "authorized"


def test_authorize_refuses_an_order_the_buyer_has_not_approved(api):
    client, fake = api
    created = _create(client, "not-approved")
    assert created.status_code == 200
    fake.order_status = "CREATED"
    response = client.post(f"/api/escales/pledges/{created.json()['id']}/authorize")
    assert response.status_code == 409
    assert "authorize" not in [call[0] for call in fake.calls]
    assert client.get(f"/api/escales/pledges/{created.json()['id']}").json()["status"] == "created"


def test_authorize_fails_closed_on_an_empty_paypal_status(api):
    client, fake = api
    created = _create(client, "empty-status")
    fake.order_status = ""
    response = client.post(f"/api/escales/pledges/{created.json()['id']}/authorize")
    assert response.status_code == 409
    assert "authorize" not in [call[0] for call in fake.calls]


def test_paypal_order_not_approved_is_409_not_502(api):
    from app.escales.paypal_client import PayPalError

    client, fake = api
    created = _create(client, "paypal-not-approved")

    def boom(order_id):
        fake.calls.append(("authorize", order_id))
        raise PayPalError(422, {"details": [{"issue": "ORDER_NOT_APPROVED"}]})

    fake.authorize_order = boom
    response = client.post(f"/api/escales/pledges/{created.json()['id']}/authorize")
    assert response.status_code == 409
    assert response.json()["detail"] == "order not approved"
    assert client.get(f"/api/escales/pledges/{created.json()['id']}").json()["status"] == "created"


def test_cabin_leg_capture_lands_in_the_leg_fund(api):
    """80 EUR captured on a cabin is the leg fund, not La Rochelle or Ajaccio."""
    import asyncio

    from app.escales.ledger import get_ledger, list_finance_entries

    client, _fake = api
    leg = "leg-la-rochelle-to-ajaccio-corse"
    _created, authorized = _ready(client, "cabin-fund", {
        "amount_eur": "80.00",
        "description": "cabine La Rochelle Ajaccio",
        "milestone_id": leg,
        "kind": "cabin_leg",
    })
    captured = client.post(f"/api/escales/pledges/{authorized['id']}/capture", headers=ADMIN)
    assert captured.status_code == 200, captured.text

    leg_fund = client.get(f"/api/escales/milestones/{leg}/fund")
    assert leg_fund.status_code == 200, leg_fund.text
    assert leg_fund.json()["income_eur"] == "80.00"
    assert leg_fund.json()["milestone_id"] == leg
    for stop in ("dep-la-rochelle", "dep-ajaccio-corse"):
        other = client.get(f"/api/escales/milestones/{stop}/fund")
        assert other.status_code == 200, other.text
        assert other.json()["income_eur"] == "0.00"

    async def stored():
        return await get_ledger().get_milestone(leg), await list_finance_entries()

    doc, entries = asyncio.run(stored())
    assert doc is not None and doc["_id"] == leg
    rows = [row for row in entries if row["kind"] == "pledge_captured"]
    assert len(rows) == 1
    assert rows[0]["milestone_id"] == leg
    assert rows[0]["amount_eur"] == "80.00"
    assert rows[0]["pledge_kind"] == "cabin_leg"


def test_leg_spending_is_charged_to_the_cabin_fund(api):
    """POST /milestones/{leg}/fund/spending writes on the leg, not 404."""
    client, _fake = api
    leg = "leg-la-rochelle-to-ajaccio-corse"
    _created, authorized = _ready(client, "cabin-spend", {
        "amount_eur": "80.00",
        "description": "cabine à dépenser",
        "milestone_id": leg,
        "kind": "cabin_leg",
    })
    assert client.post(
        f"/api/escales/pledges/{authorized['id']}/capture", headers=ADMIN
    ).status_code == 200
    locked = client.post(
        f"/api/escales/milestones/{leg}/fund/spending",
        json={"amount_eur": "20.00", "description": "avitaillement"},
    )
    assert locked.status_code == 401
    spent = client.post(
        f"/api/escales/milestones/{leg}/fund/spending",
        json={"amount_eur": "20.00", "description": "avitaillement"},
        headers=ADMIN,
    )
    assert spent.status_code == 200, spent.text
    body = spent.json()
    assert body["milestone_id"] == leg
    assert body["income_eur"] == "80.00"
    assert body["spending_eur"] == "20.00"
    assert body["balance_eur"] == "60.00"
    for stop in ("dep-la-rochelle", "dep-ajaccio-corse"):
        other = client.get(f"/api/escales/milestones/{stop}/fund").json()
        assert other["spending_eur"] == "0.00"
        assert other["income_eur"] == "0.00"
    over = client.post(
        f"/api/escales/milestones/{leg}/fund/spending",
        json={"amount_eur": "60.01", "description": "trop"},
        headers=ADMIN,
    )
    assert over.status_code == 422


def test_cabin_leg_and_the_approval_gate_stay_together(api):
    """#16 legs and the 1ed5321 approval gate, on the same service."""
    client, fake = api
    schedule = client.get("/api/escales/schedule")
    assert schedule.status_code == 200
    body = schedule.json()
    sea = next(row for row in body["legs"] if row["id"] == "leg-la-rochelle-to-ajaccio-corse")
    assert sea["capture_on"] == "departure"
    assert sea["departure_iso"] >= "2026-11-12"
    cabin = _create(client, "cabin-with-gate", {
        "amount_eur": "80.00",
        "milestone_id": "leg-la-rochelle-to-ajaccio-corse",
        "kind": "cabin_leg",
        "description": "cabine La Rochelle → Ajaccio",
        "idempotency_key": "cabin-with-gate",
    })
    assert cabin.status_code == 200, cabin.text
    assert cabin.json()["kind"] == "cabin_leg"
    assert cabin.json()["milestone_id"] == "leg-la-rochelle-to-ajaccio-corse"
    fake.order_status = "CREATED"
    refused = client.post(f"/api/escales/pledges/{cabin.json()['id']}/authorize")
    assert refused.status_code == 409
    assert "authorize" not in [call[0] for call in fake.calls]


def test_milestones_sync_the_route_when_the_ledger_is_empty(api):
    client, _fake = api
    listed = client.get("/api/escales/milestones")
    assert listed.status_code == 200
    ids = [row["id"] for row in listed.json()]
    assert ids
    assert "dep-la-rochelle" in ids
    assert ids.index("dep-fort-de-france-martinique") < ids.index("dep-dzaoudzi-mayotte")


def test_capture_refused_without_admin_key(api):
    client, fake = api
    _created, authorized = _ready(client, "cap-missing")
    response = client.post(f"/api/escales/pledges/{authorized['id']}/capture")
    assert response.status_code == 401
    assert "capture" not in [call[0] for call in fake.calls]
    assert client.get(f"/api/escales/pledges/{authorized['id']}").json()["status"] == "authorized"


def test_capture_refused_with_wrong_admin_key(api):
    client, fake = api
    _created, authorized = _ready(client, "cap-wrong")
    response = client.post(
        f"/api/escales/pledges/{authorized['id']}/capture",
        headers={"x-admin-key": "wrong-admin-key"},
    )
    assert response.status_code == 403
    assert "capture" not in [call[0] for call in fake.calls]


def test_capture_refused_when_admin_key_unset(api, monkeypatch):
    monkeypatch.delenv("ESCALES_ADMIN_KEY", raising=False)
    client, fake = api
    _created, authorized = _ready(client, "cap-unset")
    response = client.post(
        f"/api/escales/pledges/{authorized['id']}/capture",
        headers=ADMIN,
    )
    assert response.status_code == 401
    assert "capture" not in [call[0] for call in fake.calls]


def test_fund_counts_captured_income_and_treasurer_spending(api):
    client, _fake = api
    empty = client.get("/api/escales/milestones/dep-mayotte/fund")
    assert empty.status_code == 200
    assert empty.json()["income_eur"] == "0.00"
    assert empty.json()["captured_eur"] == "0.00"
    assert empty.json()["authorized_eur"] == "0.00"
    assert empty.json()["spending_eur"] == "0.00"
    assert empty.json()["balance_eur"] == "0.00"
    assert "income" not in empty.json()
    assert "pledge_id" not in empty.text

    _created, authorized = _ready(client, "fund-auth")
    held = client.get("/api/escales/milestones/dep-mayotte/fund").json()
    assert held["income_eur"] == "0.00"
    assert held["authorized_eur"] == "20.00"
    assert "income" not in held

    captured = client.post(f"/api/escales/pledges/{authorized['id']}/capture", headers=ADMIN)
    assert captured.status_code == 200
    other = _create(client, "fund-other", {**PLEDGE, "milestone_id": "dakar", "amount_eur": "60.00"})
    assert other.status_code == 200
    other_id = other.json()["id"]
    assert _authorize(client, other_id).status_code == 200
    assert client.post(f"/api/escales/pledges/{other_id}/capture", headers=ADMIN).status_code == 200

    refused = client.post(
        "/api/escales/milestones/dep-mayotte/fund/spending",
        json={"amount_eur": "5.00", "description": "gasoil"},
    )
    assert refused.status_code == 401
    bad = client.post(
        "/api/escales/milestones/dep-mayotte/fund/spending",
        json={"amount_eur": "0", "description": "gasoil"},
        headers=ADMIN,
    )
    assert bad.status_code == 422

    spent = client.post(
        "/api/escales/milestones/dep-mayotte/fund/spending",
        json={"amount_eur": "5.00", "description": "gasoil"},
        headers=ADMIN,
    )
    assert spent.status_code == 200
    fund = spent.json()
    assert fund["milestone_id"] == "dzaoudzi-mayotte"
    assert fund["currency"] == "EUR"
    assert fund["income_eur"] == "20.00"
    assert fund["spending_eur"] == "5.00"
    assert fund["balance_eur"] == "15.00"
    assert fund["overdrawn"] is False
    assert fund["captured_eur"] == "20.00"
    assert "income" not in fund
    assert "spending" not in fund
    assert "pledge_id" not in fund
    assert authorized["id"] not in str(fund)
    same = client.get("/api/escales/milestones/mayotte/fund").json()
    assert same["income_eur"] == "20.00"
    assert same["spending_eur"] == "5.00"
    dakar = client.get("/api/escales/milestones/dakar/fund").json()
    assert dakar["income_eur"] == "60.00"
    assert dakar["spending_eur"] == "0.00"
    assert dakar["balance_eur"] == "60.00"
    assert captured.json()["fund"]["milestone_id"] == "dzaoudzi-mayotte"
    assert captured.json()["fund"]["income_eur"] == "20.00"


def test_fund_rejects_bad_amounts_and_unknown_stopovers(api):
    client, _fake = api
    missing = client.get("/api/escales/milestones/nulle-part/fund")
    assert missing.status_code == 404
    for amount in ("NaN", "Infinity", "-Infinity", "1.999", "10000.01", "0"):
        response = client.post(
            "/api/escales/milestones/lorient/fund/spending",
            json={"amount_eur": amount, "description": "essai"},
            headers=ADMIN,
        )
        assert response.status_code == 422, amount
    unknown = client.post(
        "/api/escales/milestones/nulle-part/fund/spending",
        json={"amount_eur": "1.00", "description": "essai"},
        headers=ADMIN,
    )
    assert unknown.status_code == 404

    _created, authorized = _ready(client, "fund-alias")
    assert client.post(
        f"/api/escales/pledges/{authorized['id']}/capture", headers=ADMIN
    ).status_code == 200
    capped = client.post(
        "/api/escales/milestones/dep-lorient/fund/spending",
        json={"amount_eur": "10000", "description": "cale sèche"},
        headers=ADMIN,
    )
    assert capped.status_code == 422
    alias = client.get("/api/escales/milestones/lorient/fund")
    assert alias.status_code == 200
    assert alias.json()["spending_eur"] == "0.00"
    assert alias.json()["milestone_id"] == "lorient"
    exact = client.post(
        "/api/escales/milestones/dep-mayotte/fund/spending",
        json={"amount_eur": "20.00", "description": "cale sèche"},
        headers=ADMIN,
    )
    assert exact.status_code == 200, exact.text
    body = exact.json()
    assert body["milestone_id"] == "dzaoudzi-mayotte"
    assert body["overdrawn"] is False
    assert body["balance_eur"] == "0.00"
    assert body["income_eur"] == "20.00"
    over = client.post(
        "/api/escales/milestones/mayotte/fund/spending",
        json={"amount_eur": "0.01", "description": "un centime de trop"},
        headers=ADMIN,
    )
    assert over.status_code == 422
    plain = client.get("/api/escales/milestones/mayotte/fund").json()
    assert plain["spending_eur"] == "20.00"
    assert plain["income_eur"] == "20.00"
    assert plain["overdrawn"] is False


def test_capture_ok_with_admin_key(api):
    client, fake = api
    _created, authorized = _ready(client, "cap-ok")
    response = client.post(f"/api/escales/pledges/{authorized['id']}/capture", headers=ADMIN)
    assert response.status_code == 200
    assert response.json()["status"] == "captured"
    assert ("capture", "AUTH-ORDER1") in fake.calls


def test_void_records_void_id_and_voided_at(api):
    """A void keeps PayPal's id when the body has one, else the authorization id."""
    client, fake = api
    _created, authorized = _ready(client, "void-stamp")

    def void_authorization(authorization_id):
        fake.calls.append(("void", authorization_id))
        return {"id": "VOID-1", "status": "VOIDED"}

    fake.void_authorization = void_authorization
    stamped = client.post(f"/api/escales/pledges/{authorized['id']}/void", headers=ADMIN)
    assert stamped.status_code == 200, stamped.text
    body = stamped.json()
    assert body["status"] == "voided"
    assert body["void_id"] == "VOID-1"
    assert body["voided_at"].endswith("Z") or "+" in body["voided_at"]

    _other, second = _ready(client, "void-fallback")
    fake.void_authorization = lambda authorization_id: {}
    fallback = client.post(f"/api/escales/pledges/{second['id']}/void", headers=ADMIN)
    assert fallback.status_code == 200, fallback.text
    assert fallback.json()["void_id"] == second["authorization_id"]
    assert fallback.json()["voided_at"]


def test_void_with_admin_key(api):
    client, fake = api
    _created, authorized = _ready(client, "void-ok")
    missing = client.post(f"/api/escales/pledges/{authorized['id']}/void")
    assert missing.status_code == 401
    wrong = client.post(
        f"/api/escales/pledges/{authorized['id']}/void",
        headers={"x-admin-key": "wrong-admin-key"},
    )
    assert wrong.status_code == 403
    response = client.post(f"/api/escales/pledges/{authorized['id']}/void", headers=ADMIN)
    assert response.status_code == 200
    assert response.json()["status"] == "voided"
    assert ("void", "AUTH-ORDER1") in fake.calls
    assert "capture" not in [call[0] for call in fake.calls]


def test_declined_or_expired_capture_is_a_conflict(api, monkeypatch):
    """DECLINED, FAILED, or an expired hold is 409, not an unhandled 500."""
    import asyncio

    import app.routers.escales as routes
    from app.escales.ledger import get_ledger

    client, fake = api
    _created, authorized = _ready(client, "cap-expired")

    async def expire():
        doc = await get_ledger().get_pledge(authorized["id"])
        doc["authorization_expires_at"] = "2020-01-01T00:00:00Z"
        await get_ledger().save_pledge(doc)

    asyncio.run(expire())
    expired = client.post(f"/api/escales/pledges/{authorized['id']}/capture", headers=ADMIN)
    assert expired.status_code == 409
    assert "expired" in expired.json()["detail"].lower()

    _created_d, declined_pledge = _ready(client, "cap-declined")

    def declined_capture(authorization_id, final=True):
        fake.calls.append(("capture", authorization_id))
        return {"id": "CAP-D", "status": "DECLINED"}

    fake.capture_authorization = declined_capture
    declined = client.post(
        f"/api/escales/pledges/{declined_pledge['id']}/capture", headers=ADMIN,
    )
    assert declined.status_code == 409
    assert "DECLINED" in declined.json()["detail"]
    stored = client.get(f"/api/escales/pledges/{declined_pledge['id']}")
    assert stored.json()["status"] == "authorized"

    def failed_capture(authorization_id, final=True):
        fake.calls.append(("capture", authorization_id))
        return {"id": "CAP-F", "status": "FAILED"}

    _created_f, failed_pledge = _ready(client, "cap-failed")
    fake.capture_authorization = failed_capture
    failed = client.post(
        f"/api/escales/pledges/{failed_pledge['id']}/capture", headers=ADMIN,
    )
    assert failed.status_code == 409
    assert "FAILED" in failed.json()["detail"]

    async def boom(*_args, **_kwargs):
        raise ValueError("PayPal authorization has expired")

    monkeypatch.setattr(routes, "void_pledge", boom)
    voided = client.post(
        f"/api/escales/pledges/{declined_pledge['id']}/void", headers=ADMIN,
    )
    assert voided.status_code == 409
    assert "expired" in voided.json()["detail"].lower()


def test_forbidden_transition_returns_409(api):
    client, fake = api
    created = _create(client, "forbid-1")
    assert created.status_code == 200
    pledge_id = created.json()["id"]
    early = client.post(f"/api/escales/pledges/{pledge_id}/capture", headers=ADMIN)
    assert early.status_code == 409
    assert "forbidden" in early.json()["detail"]
    early_void = client.post(f"/api/escales/pledges/{pledge_id}/void", headers=ADMIN)
    assert early_void.status_code == 409
    authorized = _authorize(client, pledge_id)
    assert authorized.status_code == 200
    again = _authorize(client, pledge_id)
    assert again.status_code == 409
    captured = client.post(f"/api/escales/pledges/{pledge_id}/capture", headers=ADMIN)
    assert captured.status_code == 200
    after = client.post(f"/api/escales/pledges/{pledge_id}/void", headers=ADMIN)
    assert after.status_code == 409
    assert [call[0] for call in fake.calls].count("capture") == 1
    assert "void" not in [call[0] for call in fake.calls]


def test_evidence_flagged_simulation_for_naviguide(api):
    client, _fake = api
    response = client.post(
        "/api/escales/milestones/dep-mayotte/evidence",
        json={"met": True, "facts": {"port": "Mayotte", "boats": 12}},
        headers=ADMIN,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["flag"] == "simulation"
    assert body["provider"] == "NAVIGUIDE"
    assert body["source"] == "simulation"
    assert body["met"] is True
    listed = client.get("/api/escales/milestones")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == "dep-mayotte"
    assert listed.json()[0]["evidence"][0]["flag"] == "simulation"
    assert listed.json()[0]["evidence"][0]["provider"] == "NAVIGUIDE"


def test_captain_route_does_not_capture_or_void(api):
    client, fake = api
    _created, authorized = _ready(client, "review-1")
    evidence = client.post(
        "/api/escales/milestones/dep-mayotte/evidence",
        json={"met": True, "facts": {"port": "Mayotte"}},
        headers=ADMIN,
    )
    assert evidence.status_code == 200
    review = client.post("/api/escales/captain/review/dep-mayotte")
    assert review.status_code == 200
    body = review.json()
    assert body["proposal"] == "capture"
    assert "pledge_ids" not in body
    assert "pending_authorizations" not in body
    assert "authorization_id" not in review.text
    listed = client.get("/api/escales/milestones")
    stored = next(row for row in listed.json() if row["id"] == "dep-mayotte")
    assert "pending_authorizations" not in (stored.get("proposal") or {})
    assert "pledge_ids" not in (stored.get("proposal") or {})
    assert "authorization_id" not in listed.text
    wrong = client.post(
        "/api/escales/captain/review/dep-mayotte",
        headers={"x-admin-key": "not-the-key"},
    )
    assert wrong.status_code == 403
    assert "pending_authorizations" not in wrong.text
    assert "authorization_id" not in wrong.text
    opened = client.post("/api/escales/captain/review/dep-mayotte", headers=ADMIN)
    assert opened.status_code == 200
    pending = opened.json()["pending_authorizations"]
    assert [row["pledge_id"] for row in pending] == opened.json()["pledge_ids"]
    assert pending[0]["authorization_id"] == authorized["authorization_id"]
    assert pending[0]["status"] == "authorized"
    assert pending[0]["amount_eur"] == "20.00"
    assert pending[0]["currency"] == "EUR"
    again = client.get("/api/escales/milestones")
    assert "pending_authorizations" not in again.text
    assert "authorization_id" not in again.text
    assert body["justification"]
    names = [call[0] for call in fake.calls]
    assert "capture" not in names
    assert "void" not in names
    assert "orders.get" in names
    assert "authorizations.get" in names
    assert client.get(f"/api/escales/pledges/{authorized['id']}").json()["status"] == "authorized"


def test_review_route_passes_the_browser_language(api, monkeypatch):
    client, _fake = api
    seen = {}

    async def fake_review(milestone_id, reader=None, lang="fr"):
        seen["milestone_id"] = milestone_id
        seen["lang"] = lang
        return {"milestone_id": milestone_id, "proposal": "wait", "lang": lang}

    monkeypatch.setattr("app.routers.escales.captain_review", fake_review)
    english = client.post(
        "/api/escales/captain/review/lorient",
        headers={"accept-language": "en-GB,en;q=0.8"},
    )
    assert english.status_code == 200
    assert seen == {"milestone_id": "lorient", "lang": "en"}
    french = client.post(
        "/api/escales/captain/review/dakar",
        headers={"accept-language": "fr-FR,fr;q=0.9"},
    )
    assert french.status_code == 200
    assert seen["lang"] == "fr"
    assert seen["milestone_id"] == "dakar"


def test_audit_records_proposal_and_treasurer_actions(api):
    client, _fake = api
    client.post(
        "/api/escales/milestones/dep-mayotte/evidence",
        json={"met": True, "facts": {"port": "Mayotte"}},
        headers=ADMIN,
    )
    _created_a, authorized_a = _ready(client, "audit-a")
    dinner = {**PLEDGE, "description": "diner", "amount_eur": "60.00"}
    _created_b, authorized_b = _ready(client, "audit-b", dinner)
    review = client.post("/api/escales/captain/review/dep-mayotte")
    assert review.status_code == 200
    captured = client.post(f"/api/escales/pledges/{authorized_a['id']}/capture", headers=ADMIN)
    voided = client.post(f"/api/escales/pledges/{authorized_b['id']}/void", headers=ADMIN)
    assert captured.status_code == 200
    assert voided.status_code == 200
    entries = asyncio.run(list_entries())
    kinds = [entry["kind"] for entry in entries]
    assert kinds.count("proposal") == 1
    assert kinds.count("capture") == 1
    assert kinds.count("void") == 1
    proposal = next(entry for entry in entries if entry["kind"] == "proposal")
    assert proposal["actor"] == "captain"
    assert proposal["proposal"] == "capture"
    assert proposal["justification"]
    assert proposal["collection"] == AUDIT_COLLECTION == "escales_audit"
    capture = next(entry for entry in entries if entry["kind"] == "capture")
    assert capture["actor"] == "treasurer"
    assert capture["pledge_id"] == authorized_a["id"]
    void = next(entry for entry in entries if entry["kind"] == "void")
    assert void["pledge_id"] == authorized_b["id"]


def test_flag_disabled_returns_404(monkeypatch):
    monkeypatch.delenv("ESCALES_ENABLED", raising=False)
    monkeypatch.setenv("ESCALES_STORE", "memory")
    set_paypal_client_factory(lambda: FakePayPal())
    app = FastAPI()
    app.include_router(router)
    try:
        with TestClient(app) as client:
            assert client.get("/api/escales/milestones").status_code == 404
            created = client.post("/api/escales/pledges", json=PLEDGE, headers={"PayPal-Request-Id": "off"})
            assert created.status_code == 404
            assert client.post("/api/escales/captain/chat", json={"message": "bonjour"}).status_code == 404
    finally:
        set_paypal_client_factory(None)


def test_main_registers_escales_only_when_enabled():
    text = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    assert "ESCALES_ENABLED" in text
    assert "app.include_router(escales.router)" in text
    for line in text.splitlines():
        if line.startswith("from app.routers import") and "escales" in line:
            raise AssertionError("escales must be imported only inside the ESCALES_ENABLED branch")
    assert "\n    from app.routers import escales\n" in text
    assert "webhooks_router" in text


def test_pledge_defaults_to_mile_and_labels_the_simulated_price(api):
    client, fake = api
    response = _create(client, "m0-mile")
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "mile"
    assert body["target_id"] == "dzaoudzi-mayotte"
    assert body["intent"] == "AUTHORIZE"
    assert body["status"] == "created"
    assert body["price_label"] == "simulated price"
    assert body["simulated_price"]["label"] == "simulated price"
    assert body["simulated_price"]["simulated"] is True
    assert body["simulated_price"]["amount_eur"] == "1.00"
    assert "capture" not in [call[0] for call in fake.calls]


def test_pledge_accepts_kind_and_target(api):
    client, _fake = api
    response = _create(client, "m0-meal", {
        **PLEDGE,
        "kind": "meal",
        "target_id": "mayotte",
        "amount_eur": "60.00",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "meal"
    assert body["target_id"] == "dzaoudzi-mayotte"
    assert body["milestone_id"] == "dep-dzaoudzi-mayotte"
    assert body["simulated_price"]["amount_eur"] == "60.00"
    assert body["simulated_price"]["label"] == "simulated price"


def test_target_slug_must_be_known_for_a_stopover_kind(api):
    client, fake = api
    bad_slug = _create(client, "m0-slug", {
        **PLEDGE, "kind": "berth", "amount_eur": "30.00", "target_id": "Projet Ecole",
    })
    assert bad_slug.status_code == 422
    unknown = _create(client, "m0-unknown", {
        **PLEDGE, "kind": "care", "amount_eur": "40.00", "target_id": "nulle-part",
    })
    assert unknown.status_code == 422
    project = _create(client, "m0-project", {
        **PLEDGE,
        "kind": "project_pledge",
        "target_id": "projet-ecole",
        "amount_eur": "12.50",
    })
    assert project.status_code == 200, project.text
    assert project.json()["target_id"] == "projet-ecole"
    assert project.json()["amount_eur"] == "12.50"
    assert fake.calls[-1][0] == "create"
    other_escale = _create(client, "m0-other", {**PLEDGE, "kind": "mile", "target_id": "dakar"})
    assert other_escale.status_code == 422
    fund = _create(client, "m0-fund", {
        **PLEDGE,
        "kind": "common_fund",
        "target_id": "mayotte",
        "amount_eur": "8.00",
    })
    assert fund.status_code == 200, fund.text
    assert fund.json()["target_id"] == "dzaoudzi-mayotte"
    fund_other = _create(client, "m0-fund-other", {
        **PLEDGE,
        "kind": "common_fund",
        "target_id": "projet-ecole",
        "amount_eur": "8.00",
    })
    assert fund_other.status_code == 422


def test_unknown_pledge_kind_is_rejected(api):
    client, fake = api
    response = _create(client, "m0-bad", {**PLEDGE, "kind": "yacht"})
    assert response.status_code == 422
    assert fake.calls == []


def test_prices_and_clock(api, monkeypatch):
    monkeypatch.delenv("ESCALES_CLOCK_START", raising=False)
    monkeypatch.delenv("ESCALES_ENV", raising=False)
    client, _fake = api
    prices = client.get("/api/escales/prices")
    assert prices.status_code == 200
    catalogue = prices.json()
    assert catalogue["simulated"] is True
    assert catalogue["label"] == "simulated price"
    kinds = [row["kind"] for row in catalogue["prices"]]
    assert kinds == [
        "mile", "project_pledge", "berth", "night", "meal", "care", "cabin_leg", "common_fund",
    ]
    assert all(row["label"] == "simulated price" and row["simulated"] is True for row in catalogue["prices"])
    by_kind = {row["kind"]: row for row in catalogue["prices"]}
    assert by_kind["mile"]["amount_eur"] == "1.00"
    assert by_kind["berth"]["amount_eur"] == "30.00"
    assert by_kind["night"]["amount_eur"] == "60.00"
    assert by_kind["meal"]["amount_eur"] == "60.00"
    assert by_kind["care"]["amount_eur"] == "40.00"
    assert by_kind["cabin_leg"]["amount_eur"] == "80.00"
    assert "amount_eur" not in by_kind["project_pledge"]
    assert "amount_eur" not in by_kind["common_fund"]
    assert by_kind["project_pledge"]["free_amount"] is True
    assert by_kind["mile"]["free_amount"] is False
    assert by_kind["mile"]["indicative"] is True
    assert catalogue["indicative"] is True
    assert "indicative" in catalogue["note"].lower()
    clock = client.get("/api/escales/clock")
    assert clock.status_code == 200
    assert clock.json()["start"] == "2026-11-12"


def test_departure_clock_captures_on_the_day(api, monkeypatch):
    """The simulated clock captures on departure day, voids a cancelled stop, and refuses an early authorization."""
    import asyncio

    from app.escales.ledger import get_ledger

    client, fake = api
    departure = "2026-11-20T08:00:00+00:00"

    async def stamp(milestone_id: str) -> None:
        await get_ledger().ensure_milestone(
            milestone_id,
            meta={"capture_on": "departure", "departure_iso": departure},
        )

    def status(pledge_id: str) -> str:
        response = client.get(f"/api/escales/pledges/{pledge_id}")
        assert response.status_code == 200, response.text
        return response.json()["status"]

    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-10-21T08:00:00Z")
    from app.escales.naviguide_bridge import resolve_milestone

    sailing = resolve_milestone("dep-la-rochelle")
    assert sailing
    asyncio.run(stamp(sailing))
    creates = [call for call in fake.calls if call[0] == "create"]
    early = _create(client, "dep-early", {
        **PLEDGE,
        "milestone_id": "dep-la-rochelle",
        "description": "trop tot",
    })
    assert early.status_code == 422
    assert "29" in early.text
    assert [call for call in fake.calls if call[0] == "create"] == creates

    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-19T08:00:00Z")
    held_body, held = _ready(client, "dep-held", {
        **PLEDGE,
        "milestone_id": sailing,
        "description": "veille du depart",
    })
    assert held["status"] == "authorized"
    before = client.post("/api/escales/clock/settle", headers=ADMIN)
    assert before.status_code == 200
    assert before.json()["settled"]["actions"] == [{"pledge_id": held["id"], "action": "wait"}]
    assert status(held["id"]) == "authorized"
    assert all(call[0] != "capture" for call in fake.calls)

    stopped_body, stopped = _ready(client, "dep-cancel", {
        **PLEDGE,
        "description": "escale annulee",
    })
    asyncio.run(stamp(stopped_body["milestone_id"]))
    evidence = client.post(
        f"/api/escales/milestones/{stopped_body['milestone_id']}/evidence",
        json={"met": False, "facts": {"cancelled": True}},
        headers=ADMIN,
    )
    assert evidence.status_code == 200, evidence.text
    voided = client.post("/api/escales/clock/settle", headers=ADMIN)
    assert voided.status_code == 200
    actions = {row["pledge_id"]: row["action"] for row in voided.json()["settled"]["actions"]}
    assert actions[stopped["id"]] == "void"
    assert actions[held["id"]] == "wait"
    assert status(stopped["id"]) == "voided"
    assert status(held["id"]) == "authorized"
    assert any(call[0] == "void" for call in fake.calls)
    assert all(call[0] != "capture" for call in fake.calls)

    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-20T08:00:00Z")
    public = client.get("/api/escales/clock")
    assert public.status_code == 200
    assert "settled" not in public.json()
    assert public.json()["now"].startswith("2026-11-20")
    assert status(held["id"]) == "authorized"
    locked = client.post("/api/escales/clock/settle")
    assert locked.status_code == 401
    departed = client.post("/api/escales/clock/settle", headers=ADMIN)
    assert departed.status_code == 200
    assert departed.json()["settled"]["actions"] == [{"pledge_id": held["id"], "action": "capture"}]
    assert status(held["id"]) == "captured"
    assert any(call[0] == "capture" for call in fake.calls)


def test_declined_capture_does_not_stop_the_clock(api, monkeypatch):
    """One DECLINED capture is recorded and the next pledge still settles."""
    import asyncio

    from app.escales.ledger import get_ledger

    client, fake = api
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-20T08:00:00Z")

    async def stamp(milestone_id: str) -> None:
        await get_ledger().ensure_milestone(milestone_id, meta={
            "capture_on": "departure",
            "departure_iso": "2026-11-20T08:00:00+00:00",
        })

    first_body = _create(client, "clock-declined", {
        **PLEDGE, "milestone_id": "dep-la-rochelle", "description": "refusee",
    })
    assert first_body.status_code == 200, first_body.text
    asyncio.run(stamp(first_body.json()["milestone_id"]))
    first = _authorize(client, first_body.json()["id"])
    assert first.status_code == 200, first.text
    second = _ready(client, "clock-next", {
        **PLEDGE,
        "milestone_id": first_body.json()["milestone_id"],
        "description": "la suivante",
    })[1]

    def capture_authorization(authorization_id, final=True):
        fake.calls.append(("capture", authorization_id))
        if authorization_id == first.json()["authorization_id"]:
            return {"id": "CAP-D", "status": "DECLINED"}
        return {"id": "CAP-OK", "status": "COMPLETED"}

    fake.capture_authorization = capture_authorization
    clock = client.post("/api/escales/clock/settle", headers=ADMIN)
    assert clock.status_code == 200, clock.text
    actions = {row["pledge_id"]: row for row in clock.json()["settled"]["actions"]}
    assert actions[first.json()["id"]]["action"] == "error"
    assert "DECLINED" in actions[first.json()["id"]]["detail"]
    assert actions[second["id"]]["action"] == "capture"
    again = client.post("/api/escales/clock/settle", headers=ADMIN)
    assert again.status_code == 200, again.text
    assert client.get(f"/api/escales/pledges/{second['id']}").json()["status"] == "captured"


def test_cancelled_leg_rejects_a_new_authorization(api):
    client, fake = api
    leg = "leg-la-rochelle-to-ajaccio-corse"
    created = _create(client, "cabin-before-cancel", {
        "amount_eur": "80.00",
        "description": "cabine avant annulation",
        "milestone_id": leg,
        "kind": "cabin_leg",
    })
    assert created.status_code == 200, created.text
    evidence = client.post(
        f"/api/escales/milestones/{leg}/evidence",
        json={"met": False, "facts": {"cancelled": True}},
        headers=ADMIN,
    )
    assert evidence.status_code == 200, evidence.text
    refused = _authorize(client, created.json()["id"])
    assert refused.status_code == 422
    assert "cancelled" in refused.json()["detail"]
    creates = [call for call in fake.calls if call[0] == "create"]
    again = _create(client, "cabin-after-cancel", {
        "amount_eur": "80.00",
        "description": "cabine après annulation",
        "milestone_id": leg,
        "kind": "cabin_leg",
    })
    assert again.status_code == 422
    assert "cancelled" in again.json()["detail"]
    assert [call for call in fake.calls if call[0] == "create"] == creates
    assert all(call[0] != "authorize" for call in fake.calls)


def test_clock_start_is_configurable_outside_production(monkeypatch):
    from app.escales.config import clock_start

    monkeypatch.setenv("ESCALES_ENV", "production")
    monkeypatch.delenv("ESCALES_CLOCK_START", raising=False)
    assert clock_start() == "2026-11-12"
    monkeypatch.setenv("ESCALES_ENV", "development")
    monkeypatch.setenv("ESCALES_CLOCK_START", "2026-12-01")
    assert clock_start() == "2026-12-01"
    monkeypatch.setenv("ESCALES_ENV", "test")
    monkeypatch.setenv("ESCALES_CLOCK_START", "2027-01-03T08:00:00Z")
    assert clock_start() == "2027-01-03"
    monkeypatch.setenv("ESCALES_CLOCK_START", "2026-11-12T03:00:00Z")
    assert clock_start() == "2026-11-11"
    monkeypatch.setenv("ESCALES_CLOCK_START", "tomorrow")
    assert clock_start() == "2026-11-12"


def test_schedule_local_fallback(api, monkeypatch):
    monkeypatch.delenv("ESCALES_CLOCK_START", raising=False)
    monkeypatch.delenv("ESCALES_ENV", raising=False)
    client, _fake = api
    response = client.get("/api/escales/schedule")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "local"
    ids = [row["_id"] for row in body["milestones"]]
    assert "dep-la-rochelle" in ids
    assert "dep-fort-de-france-martinique" in ids
    assert "dep-dzaoudzi-mayotte" in ids
    assert ids.index("dep-fort-de-france-martinique") < ids.index("dep-dzaoudzi-mayotte")
    shown = next(row for row in body["milestones"] if row["_id"] == "dep-fort-de-france-martinique")
    assert shown["display_name"] == "Fort-de-France (Martinique)"
    assert "dep-" not in shown["display_name"].lower()
    assert body["export"]["escales"][0]["arrival_iso"].startswith("2026-11-12")
    assert body["clock"]["start"] == "2026-11-12"
    assert len(body["legs"]) == 15
    cabin = next(row for row in body["legs"] if row["id"] == "leg-la-rochelle-to-ajaccio-corse")
    assert cabin["capture_on"] == "departure"
    assert cabin["departure_iso"].startswith("2026-11-12T12:00:00")
    shown = next(row for row in body["milestones"] if row["_id"] == cabin["id"])
    assert shown["display_name"] == "La Rochelle → Ajaccio (Corse)"
    assert shown["capture_on"] == "departure"
    land = next(row for row in body["legs"] if row["id"] == "leg-saint-maur-berry-indre-to-la-rochelle")
    assert land["departure_iso"] < land["arrival_iso"]
    listed = client.get("/api/escales/milestones")
    assert listed.status_code == 200
    listed_ids = [row["id"] for row in listed.json()]
    assert "dep-la-rochelle" in listed_ids
    assert body["prices"]["label"] == "simulated price"
    assert body["prices"]["simulated"] is True


def test_public_fund_and_pledge_share_the_aggregate(api):
    """A stopover fund is public totals. Pledge reads use that same object."""
    client, _fake = api
    created = _create(client, "pub-fund").json()
    listed = client.get(f"/api/escales/pledges/{created['id']}")
    assert listed.status_code == 200
    body = listed.json()
    assert set(body) == {"status", "amount_eur", "fund"}
    assert body["status"] == "created"
    assert body["amount_eur"] == "20.00"
    fund = client.get("/api/escales/milestones/dep-mayotte/fund")
    assert fund.status_code == 200
    assert fund.json() == body["fund"] == created["fund"]
    assert "income" not in fund.json()
    assert "pledge_id" not in fund.text
    assert "pledge_ids" not in fund.text
    assert "pledge_ids" not in created
    refused = client.post(
        "/api/escales/milestones/dep-mayotte/fund/spending",
        json={"amount_eur": "1.00", "description": "sans clé"},
    )
    assert refused.status_code == 401
    wrong = client.get(
        f"/api/escales/pledges/{created['id']}",
        headers={"x-admin-key": "nope"},
    )
    assert wrong.status_code == 403


def test_unplaced_project_and_fund_totals_are_readable(api):
    """Project and common-fund totals need the treasurer key. A stopover stays public."""
    client, _fake = api
    locked_project = client.get("/api/escales/milestones/project/fund")
    assert locked_project.status_code == 401
    locked_fund = client.get("/api/escales/milestones/fund/fund")
    assert locked_fund.status_code == 401
    assert "income_eur" not in locked_project.text
    assert "income_eur" not in locked_fund.text
    empty_project = client.get("/api/escales/milestones/project/fund", headers=ADMIN)
    assert empty_project.status_code == 200
    assert empty_project.json()["milestone_id"] == "projet"
    assert empty_project.json()["income_eur"] == "0.00"
    assert empty_project.json()["spending_eur"] == "0.00"
    assert empty_project.json()["balance_eur"] == "0.00"
    assert "income" not in empty_project.json()
    assert "pledge_id" not in empty_project.text
    empty_fund = client.get("/api/escales/milestones/fund/fund", headers=ADMIN)
    assert empty_fund.status_code == 200
    assert empty_fund.json()["milestone_id"] == "fonds-commun"

    _created_p, project = _ready(client, "tot-project", {
        "amount_eur": "15.00",
        "description": "promesse projet",
        "milestone_id": "",
        "kind": "project_pledge",
    })
    assert client.post(
        f"/api/escales/pledges/{project['id']}/capture", headers=ADMIN
    ).status_code == 200
    _ready(client, "tot-project-held", {
        "amount_eur": "7.00",
        "description": "projet encore autorisé",
        "milestone_id": "",
        "kind": "project_pledge",
    })
    shown = client.get("/api/escales/milestones/projet/fund", headers=ADMIN).json()
    assert shown["income_eur"] == "15.00"
    assert shown["captured_eur"] == "15.00"
    assert shown["authorized_eur"] == "7.00"
    assert shown["balance_eur"] == "15.00"
    assert "income" not in shown
    assert "pledge_ids" not in shown
    assert project["id"] not in str(shown)

    _created_f, boat = _ready(client, "tot-fund", {
        "amount_eur": "12.00",
        "description": "fonds commun",
        "milestone_id": "",
        "kind": "common_fund",
    })
    assert client.post(
        f"/api/escales/pledges/{boat['id']}/capture", headers=ADMIN
    ).status_code == 200
    fund = client.get("/api/escales/milestones/fonds-commun/fund", headers=ADMIN).json()
    assert fund["income_eur"] == "12.00"
    assert fund["spending_eur"] == "0.00"
    assert fund["balance_eur"] == "12.00"
    assert client.get("/api/escales/milestones/common-fund/fund", headers=ADMIN).json()["income_eur"] == "12.00"
    assert client.get("/api/escales/milestones/project/fund", headers=ADMIN).json()["income_eur"] == "15.00"
    assert client.get("/api/escales/milestones/common-fund/fund").status_code == 401
    assert client.get("/api/escales/milestones/projet/fund").status_code == 401

    _created_s, stop = _ready(client, "tot-stop-fund", {
        **PLEDGE,
        "kind": "common_fund",
        "amount_eur": "9.00",
        "description": "caisse de l'escale",
    })
    assert client.post(
        f"/api/escales/pledges/{stop['id']}/capture", headers=ADMIN
    ).status_code == 200
    assert client.get("/api/escales/milestones/mayotte/fund").json()["income_eur"] == "9.00"
    assert client.get("/api/escales/milestones/fund/fund", headers=ADMIN).json()["income_eur"] == "12.00"

    refused = client.post(
        "/api/escales/milestones/project/fund/spending",
        json={"amount_eur": "1.00", "description": "hors lecture"},
        headers=ADMIN,
    )
    assert refused.status_code == 404
    assert client.get("/api/escales/milestones/nulle-part/fund").status_code == 404


def _capture_open_and_stopover(client):
    """15.00 on the project, 12.00 on the boat fund, 9.00 on Mayotte."""
    _created_p, project = _ready(client, "chat-project", {
        "amount_eur": "15.00",
        "description": "promesse projet",
        "milestone_id": "",
        "kind": "project_pledge",
    })
    assert client.post(
        f"/api/escales/pledges/{project['id']}/capture", headers=ADMIN
    ).status_code == 200
    _created_f, boat = _ready(client, "chat-boat", {
        "amount_eur": "12.00",
        "description": "fonds commun",
        "milestone_id": "",
        "kind": "common_fund",
    })
    assert client.post(
        f"/api/escales/pledges/{boat['id']}/capture", headers=ADMIN
    ).status_code == 200
    _created_s, stop = _ready(client, "chat-stop", {
        **PLEDGE,
        "kind": "common_fund",
        "amount_eur": "9.00",
        "description": "caisse de l'escale",
    })
    assert client.post(
        f"/api/escales/pledges/{stop['id']}/capture", headers=ADMIN
    ).status_code == 200


def test_public_chat_withholds_project_and_common_fund_totals(api):
    """The chat must not repeat the totals the fund route already locks."""
    client, _fake = api
    _capture_open_and_stopover(client)
    project = client.post(
        "/api/escales/captain/chat",
        json={"message": "How much money is in the project fund?"},
    )
    assert project.status_code == 200, project.text
    assert project.json()["fund"] is None
    assert "Only the treasurer can see this fund's totals." in project.json()["reply"]
    assert "15.00" not in project.text
    assert "15,00" not in project.text
    assert "income_eur" not in project.text
    boat = client.post(
        "/api/escales/captain/chat",
        json={"message": "Quel est le solde du fonds commun ?"},
    )
    assert boat.status_code == 200, boat.text
    assert boat.json()["fund"] is None
    assert "Seul le trésorier peut voir les totaux de cette caisse." in boat.json()["reply"]
    assert "12.00" not in boat.text
    assert "12,00" not in boat.text
    wrong = client.post(
        "/api/escales/captain/chat",
        json={"message": "How much money is in the project fund?"},
        headers={"x-admin-key": "not-the-key"},
    )
    assert wrong.status_code == 403
    assert "15.00" not in wrong.text
    assert "income_eur" not in wrong.text
    local = client.post(
        "/api/escales/captain/chat",
        json={"message": "Quel est le solde du fonds commun à Mayotte ?"},
    )
    assert local.status_code == 200, local.text
    assert local.json()["fund"]["income_eur"] == "9.00"
    assert "9,00" in local.json()["reply"]
    assert "la caisse de Dzaoudzi (Mayotte)" in local.json()["reply"]


def test_treasurer_chat_returns_project_and_common_fund_totals(api):
    client, _fake = api
    _capture_open_and_stopover(client)
    project = client.post(
        "/api/escales/captain/chat",
        json={"message": "How much money is in the project fund?"},
        headers=ADMIN,
    )
    assert project.status_code == 200, project.text
    assert project.json()["fund"]["milestone_id"] == "projet"
    assert project.json()["fund"]["balance_eur"] == "15.00"
    assert "15.00 EUR" in project.json()["reply"]
    boat = client.post(
        "/api/escales/captain/chat",
        json={"message": "Quel est le solde du fonds commun ?"},
        headers=ADMIN,
    )
    assert boat.status_code == 200, boat.text
    assert boat.json()["fund"]["milestone_id"] == "fonds-commun"
    assert boat.json()["fund"]["balance_eur"] == "12.00"
    assert "12,00" in boat.json()["reply"]


def test_project_and_fund_accept_an_empty_milestone(api):
    client, _fake = api
    project = _create(client, "proj-empty", {
        "amount_eur": "15.00",
        "description": "promesse projet",
        "milestone_id": "",
        "kind": "project_pledge",
    })
    assert project.status_code == 200, project.text
    assert project.json()["milestone_id"] == ""
    assert project.json()["target_id"] == "projet"
    fund = _create(client, "fund-empty", {
        "amount_eur": "12.00",
        "description": "fonds commun",
        "milestone_id": "",
        "kind": "common_fund",
    })
    assert fund.status_code == 200, fund.text
    assert fund.json()["milestone_id"] == ""
    assert fund.json()["target_id"] == "fonds-commun"


def test_return_and_cancel_allow_the_public_url_and_this_service(api, monkeypatch):
    monkeypatch.setenv("ESCALES_PUBLIC_URL", "https://public.example/escales")
    client, _fake = api
    allowed = _create(client, "urls-ok", {
        **PLEDGE,
        "return_url": "https://public.example/back",
        "cancel_url": "https://public.example/cancel",
    })
    assert allowed.status_code == 200, allowed.text
    own = _create(client, "urls-own", {
        **PLEDGE,
        "return_url": "http://testserver/done",
        "cancel_url": "http://testserver/stop",
    })
    assert own.status_code == 200, own.text
    bad_return = _create(client, "urls-bad-return", {**PLEDGE, "return_url": "https://evil.example/back"})
    assert bad_return.status_code == 422
    bad_cancel = _create(client, "urls-bad-cancel", {**PLEDGE, "cancel_url": "https://evil.example/cancel"})
    assert bad_cancel.status_code == 422
    assert "cancel_url" in bad_cancel.json()["detail"]


def test_priced_kind_requires_its_unit_price(api):
    client, _fake = api
    low = _create(client, "cabin-50", {
        **PLEDGE,
        "kind": "cabin_leg",
        "amount_eur": "50.00",
        "milestone_id": "leg-la-rochelle-to-ajaccio-corse",
        "description": "cabine",
    })
    assert low.status_code == 422
    assert "80.00" in low.json()["detail"]
    priced = _create(client, "cabin-80", {
        **PLEDGE,
        "kind": "cabin_leg",
        "amount_eur": "80.00",
        "milestone_id": "leg-la-rochelle-to-ajaccio-corse",
        "description": "cabine",
    })
    assert priced.status_code == 200, priced.text
    above = _create(client, "cabin-90", {
        **PLEDGE,
        "kind": "cabin_leg",
        "amount_eur": "90.00",
        "milestone_id": "leg-la-rochelle-to-ajaccio-corse",
        "description": "cabine",
    })
    assert above.status_code == 422
    assert "80.00" in above.json()["detail"]
    for kind, price, wrong in (
        ("berth", "30.00", "31.00"),
        ("night", "60.00", "120.00"),
        ("meal", "60.00", "61.00"),
        ("care", "40.00", "39.00"),
    ):
        off = _create(client, f"{kind}-off", {
            **PLEDGE,
            "kind": kind,
            "amount_eur": wrong,
            "description": kind,
        })
        assert off.status_code == 422, kind
        assert price in off.json()["detail"]
        on = _create(client, f"{kind}-on", {
            **PLEDGE,
            "kind": kind,
            "amount_eur": price,
            "description": kind,
        })
        assert on.status_code == 200, on.text
    mile = _create(client, "mile-20", {**PLEDGE, "kind": "mile", "amount_eur": "20.00"})
    assert mile.status_code == 200, mile.text
    under = _create(client, "mile-half", {**PLEDGE, "kind": "mile", "amount_eur": "0.50"})
    assert under.status_code == 422
    assert "1.00" in under.json()["detail"]
    gift = _create(client, "project-small", {
        "amount_eur": "5.00",
        "description": "promesse projet",
        "milestone_id": "",
        "kind": "project_pledge",
        "target_id": "projet-ecole",
    })
    assert gift.status_code == 200, gift.text
    project_under = _create(client, "project-half", {
        "amount_eur": "0.50",
        "description": "promesse projet",
        "milestone_id": "",
        "kind": "project_pledge",
        "target_id": "projet-ecole",
    })
    assert project_under.status_code == 422
    assert "1.00" in project_under.json()["detail"]


def test_target_id_and_milestone_id_are_documented():
    from app.routers.escales import PledgeIn

    schema = PledgeIn.model_json_schema()
    milestone = schema["properties"]["milestone_id"]["description"]
    target = schema["properties"]["target_id"]["description"]
    assert "target_id" in milestone
    assert "milestone_id" in target
    assert "leg" in target
    assert "projet" in target
    assert "fonds-commun" in target


def test_features_flags_off_by_default(api):
    client, _fake = api
    flags = client.get("/api/escales/features").json()
    assert flags["naviguide_bridge"] is False
    assert flags["bryntum"] is False
    assert flags["vault"] is False
    assert flags["webhooks_enabled"] is False
    assert flags["webhook_url"] == "https://bi-escales-api.onrender.com/api/escales/webhooks/paypal"


def test_cors_allows_the_minimix_vite_origin(monkeypatch):
    from fastapi.middleware.cors import CORSMiddleware

    monkeypatch.delenv("ESCALES_CORS_ORIGINS", raising=False)
    assert "http://localhost:5173" in cors_origins()
    assert paypal_webhook_url().endswith("/api/escales/webhooks/paypal")
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "PayPal-Request-Id", "x-admin-key"],
    )

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    with TestClient(app) as client:
        allowed = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,paypal-request-id",
            },
        )
        assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
        blocked = client.get("/api/health", headers={"Origin": "https://evil.example"})
        assert blocked.headers.get("access-control-allow-origin") is None


def test_evidence_requires_the_admin_key(api):
    client, _fake = api
    denied = client.post(
        "/api/escales/milestones/dep-mayotte/evidence",
        json={"met": True, "facts": {"port": "Mayotte"}},
    )
    assert denied.status_code == 401
    opened = client.post(
        "/api/escales/milestones/dep-mayotte/evidence",
        json={"met": True, "facts": {"port": "Mayotte"}},
        headers=ADMIN,
    )
    assert opened.status_code == 200


def test_treasurer_reads_the_pledge_queue_from_the_server(api):
    client, _fake = api
    created = _create(client, "queue-server")
    assert created.status_code == 200
    denied = client.get("/api/escales/pledges")
    assert denied.status_code == 401
    listed = client.get("/api/escales/pledges", headers=ADMIN)
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == created.json()["id"]


def test_vault_stays_off_unless_escales_vault_enabled(monkeypatch):
    from app.escales.config import vault_enabled

    monkeypatch.delenv("ESCALES_VAULT_ENABLED", raising=False)
    assert vault_enabled() is False
    monkeypatch.setenv("ESCALES_VAULT_ENABLED", "true")
    assert vault_enabled() is True
    text = (Path(__file__).resolve().parents[2] / "render.yaml").read_text(encoding="utf-8")
    start = text.index("key: ESCALES_VAULT_ENABLED")
    window = text[start:start + 80]
    assert 'value: "false"' in window
    assert 'value: "true"' not in window
