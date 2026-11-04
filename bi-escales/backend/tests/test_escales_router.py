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
from app.routers.escales import router, set_paypal_client_factory

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
        return {"id": order_id, "status": "APPROVED"}

    def get_authorization(self, authorization_id):
        self.calls.append(("authorizations.get", authorization_id))
        return {"id": authorization_id, "status": "CREATED"}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin-key")
    monkeypatch.delenv("ESCALES_TOOLKIT_ENABLED", raising=False)
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
    fetched = client.get(f"/api/escales/pledges/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["authorization_id"] == "AUTH-ORDER1"
    assert fetched.json()["status"] == "authorized"


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


def test_capture_ok_with_admin_key(api):
    client, fake = api
    _created, authorized = _ready(client, "cap-ok")
    response = client.post(f"/api/escales/pledges/{authorized['id']}/capture", headers=ADMIN)
    assert response.status_code == 200
    assert response.json()["status"] == "captured"
    assert ("capture", "AUTH-ORDER1") in fake.calls


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
    )
    assert evidence.status_code == 200
    review = client.post("/api/escales/captain/review/dep-mayotte")
    assert review.status_code == 200
    body = review.json()
    assert body["proposal"] == "capture"
    assert authorized["id"] in body["pledge_ids"]
    assert body["justification"]
    names = [call[0] for call in fake.calls]
    assert "capture" not in names
    assert "void" not in names
    assert "orders.get" in names
    assert "authorizations.get" in names
    assert client.get(f"/api/escales/pledges/{authorized['id']}").json()["status"] == "authorized"


def test_audit_records_proposal_and_treasurer_actions(api):
    client, _fake = api
    client.post(
        "/api/escales/milestones/dep-mayotte/evidence",
        json={"met": True, "facts": {"port": "Mayotte"}},
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


def test_schedule_local_fallback(api):
    client, _fake = api
    response = client.get("/api/escales/schedule")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "local"
    assert any(row["_id"] == "dep-mayotte" for row in body["milestones"])


def test_features_flags_off_by_default(api):
    client, _fake = api
    flags = client.get("/api/escales/features").json()
    assert flags["naviguide_bridge"] is False
    assert flags["bryntum"] is False

