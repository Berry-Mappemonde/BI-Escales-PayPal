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


def test_fund_counts_captured_income_and_treasurer_spending(api):
    client, _fake = api
    empty = client.get("/api/escales/milestones/dep-mayotte/fund")
    assert empty.status_code == 200
    assert empty.json()["income_eur"] == "0.00"
    assert empty.json()["spending_eur"] == "0.00"
    assert empty.json()["balance_eur"] == "0.00"
    assert empty.json()["income"] == []

    _created, authorized = _ready(client, "fund-auth")
    held = client.get("/api/escales/milestones/dep-mayotte/fund").json()
    assert held["income_eur"] == "0.00"
    assert held["income"] == []

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
    assert fund["milestone_id"] == "mayotte"
    assert fund["currency"] == "EUR"
    assert fund["income_eur"] == "20.00"
    assert fund["spending_eur"] == "5.00"
    assert fund["balance_eur"] == "15.00"
    assert fund["overdrawn"] is False
    assert fund["income"][0]["kind"] == "pledge_captured"
    assert fund["income"][0]["pledge_id"] == authorized["id"]
    assert fund["income"][0]["description"] == "20 milles Mayotte"
    assert fund["income"][0]["pledge_kind"] == "mile"
    assert fund["income"][0]["target_id"] == "mayotte"
    assert fund["spending"][0]["description"] == "gasoil"
    assert fund["spending"][0]["amount_eur"] == "5.00"
    same = client.get("/api/escales/milestones/mayotte/fund").json()
    assert same["income_eur"] == "20.00"
    assert same["spending_eur"] == "5.00"
    dakar = client.get("/api/escales/milestones/dakar/fund").json()
    assert dakar["income_eur"] == "60.00"
    assert dakar["spending_eur"] == "0.00"
    assert dakar["balance_eur"] == "60.00"
    assert captured.json()["fund"]["milestone_id"] == "mayotte"
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
    assert body["milestone_id"] == "mayotte"
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
    assert body["target_id"] == "mayotte"
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
    assert body["target_id"] == "mayotte"
    assert body["milestone_id"] == "dep-mayotte"
    assert body["simulated_price"]["amount_eur"] == "60.00"
    assert body["simulated_price"]["label"] == "simulated price"


def test_target_slug_must_be_known_for_a_stopover_kind(api):
    client, fake = api
    bad_slug = _create(client, "m0-slug", {**PLEDGE, "kind": "berth", "target_id": "Projet Ecole"})
    assert bad_slug.status_code == 422
    unknown = _create(client, "m0-unknown", {**PLEDGE, "kind": "care", "target_id": "nulle-part"})
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
    assert fund.json()["target_id"] == "mayotte"
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
    assert any(row["_id"] == "dep-mayotte" for row in body["milestones"])
    shown = next(row for row in body["milestones"] if row["_id"] == "dep-fort-de-france")
    assert shown["display_name"] == "Fort-de-France"
    assert "dep-" not in shown["display_name"].lower()
    assert body["clock"]["start"] == "2026-11-12"
    assert len(body["legs"]) == 15
    cabin = next(row for row in body["legs"] if row["id"] == "leg-la-rochelle-to-ajaccio-corse")
    assert cabin["capture_on"] == "departure"
    assert cabin["departure_iso"].startswith("2026-11-12T08:00:00")
    shown = next(row for row in body["milestones"] if row["_id"] == cabin["id"])
    assert shown["display_name"] == "La Rochelle → Ajaccio (Corse)"
    assert shown["capture_on"] == "departure"
    assert body["prices"]["label"] == "simulated price"
    assert body["prices"]["simulated"] is True


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
