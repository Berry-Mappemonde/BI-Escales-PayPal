"""A14: one public, read-only summary of where the money goes (no treasurer key)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.pledges import reset_ledger
from app.routers import escales as escales_router
from app.routers.escales import router, set_paypal_client_factory
from tests.test_escales_router import ADMIN, FakePayPal, _approve_capture, _create, _ready

URL = "/api/escales/funds/public"
LEG = "leg-la-rochelle-to-ajaccio-corse"
ZERO = {"authorized_eur": "0.00", "captured_eur": "0.00", "refunded_eur": "0.00"}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin-key")
    monkeypatch.delenv("ESCALES_DEMO_TREASURER", raising=False)
    reset_ledger()
    set_paypal_client_factory(lambda: FakePayPal())
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client
    set_paypal_client_factory(None)
    reset_ledger()


def _stop(client, key, amount="20.00", milestone="dep-la-rochelle", **extra):
    return _ready(client, key, {"amount_eur": amount, "description": "secret donor phrase", "milestone_id": milestone, **extra})


def _capture(client, pledge):
    _approve_capture(pledge["milestone_id"])
    captured = client.post(f"/api/escales/pledges/{pledge['id']}/capture", headers=ADMIN)
    assert captured.status_code == 200, captured.text


def test_empty_ledger_lists_nothing_and_a_zero_common_fund(api):
    response = api.get(URL)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "currency": "EUR",
        "stops": [],
        "legs": [],
        "projects": [],
        "common_fund": ZERO,
        "truncated": False,
    }


def test_needs_no_key_and_ignores_one(api):
    _stop(api, "pub-key")
    assert api.get(URL).json() == api.get(URL, headers=ADMIN).json()


def test_an_authorised_stop_pledge_is_held_not_captured(api):
    _stop(api, "pub-a", "20.00")
    _stop(api, "pub-b", "5.50")
    body = api.get(URL).json()
    assert body["stops"] == [
        {"milestone_id": "dep-la-rochelle", "fund_id": "la-rochelle", "authorized_eur": "25.50", "captured_eur": "0.00", "refunded_eur": "0.00"},
    ]
    assert body["legs"] == [] and body["projects"] == []


def test_matches_the_single_fund_route_for_every_listed_fund(api, monkeypatch):
    _created, held = _stop(api, "pub-match-1", "20.00")
    _created, to_capture = _stop(api, "pub-match-2", "30.00", milestone="dep-ajaccio-corse")
    # The boat has reached Ajaccio: the treasurer may capture that stop's pledge.
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-12-05T08:00:00Z")
    _capture(api, to_capture)
    body = api.get(URL).json()
    assert [row["milestone_id"] for row in body["stops"]] == ["dep-ajaccio-corse", "dep-la-rochelle"]
    for row in body["stops"]:
        single = api.get(f"/api/escales/milestones/{row['milestone_id']}/fund").json()
        assert {key: single[key] for key in ZERO} == {key: row[key] for key in ZERO}
    assert held["status"] == "authorized"
    assert body["stops"][0]["captured_eur"] == "30.00"
    assert body["stops"][0]["authorized_eur"] == "0.00"


def test_a_cabin_is_a_leg_total_not_a_stop_total(api):
    _created, cabin = _ready(api, "pub-cabin", {"amount_eur": "80.00", "description": "cabine", "milestone_id": LEG, "kind": "cabin_leg"})
    _capture(api, cabin)
    body = api.get(URL).json()
    assert body["stops"] == []
    assert body["legs"] == [
        {"milestone_id": LEG, "fund_id": LEG, "authorized_eur": "0.00", "captured_eur": "80.00", "refunded_eur": "0.00"},
    ]


def test_project_donations_and_the_common_fund(api):
    for key, amount in (("pub-p1", "25.00"), ("pub-p2", "10.00")):
        _ready(api, key, {"amount_eur": amount, "description": "don", "milestone_id": "", "kind": "project_pledge", "target_id": "projet-ecole"})
    _created, boat = _ready(api, "pub-fund", {"amount_eur": "12.00", "description": "fonds commun", "milestone_id": "", "kind": "common_fund"})
    assert boat["status"] == "captured"
    body = api.get(URL).json()
    assert body["projects"] == [
        {"project_id": "projet-ecole", "amount_eur": "35.00", "donation_count": 2, "refunded_eur": "0.00"},
    ]
    assert body["common_fund"] == {"authorized_eur": "0.00", "captured_eur": "12.00", "refunded_eur": "0.00"}
    # Same numbers as the two existing public routes.
    assert api.get("/api/escales/projects/projet-ecole/fund").json()["amount_eur"] == "35.00"
    assert api.get("/api/escales/common-fund/fund").json()["captured_eur"] == "12.00"
    # Neither is a stop or a leg.
    assert body["stops"] == [] and body["legs"] == []


def test_a_pledge_that_was_never_approved_is_not_money(api):
    created = _create(api, "pub-created", {"amount_eur": "20.00", "description": "x", "milestone_id": "dep-la-rochelle"})
    assert created.status_code == 200, created.text
    assert api.get(URL).json()["stops"] == []


def test_a_voided_pledge_leaves_the_list(api):
    _created, held = _stop(api, "pub-void")
    assert api.get(URL).json()["stops"][0]["authorized_eur"] == "20.00"
    voided = api.post(f"/api/escales/pledges/{held['id']}/void", headers=ADMIN)
    assert voided.status_code == 200, voided.text
    assert api.get(URL).json()["stops"] == []


def test_carries_amounts_only(api):
    _created, held = _stop(api, "pub-private", contributor="someone@example.com")
    _ready(api, "pub-private-p", {"amount_eur": "9.00", "description": "secret donor phrase", "milestone_id": "", "kind": "project_pledge", "target_id": "projet-ecole", "contributor": "someone@example.com"})
    response = api.get(URL)
    text = response.text
    for private in ("someone@example.com", "secret donor phrase", held["id"], "ORDER", "AUTH"):
        assert private not in text
    body = response.json()
    assert set(body) == {"currency", "stops", "legs", "projects", "common_fund", "truncated"}
    assert set(body["stops"][0]) == {"milestone_id", "fund_id", "authorized_eur", "captured_eur", "refunded_eur"}
    assert set(body["projects"][0]) == {"project_id", "amount_eur", "donation_count", "refunded_eur"}


def test_reads_a_bounded_number_of_funds(api, monkeypatch):
    monkeypatch.setattr(escales_router, "_PUBLIC_FUNDS_MAX", 1)
    _stop(api, "pub-cap-1", milestone="dep-la-rochelle")
    _stop(api, "pub-cap-2", milestone="dep-ajaccio-corse")
    body = api.get(URL).json()
    assert len(body["stops"]) == 1
    assert body["truncated"] is True


def test_is_read_only(api):
    _stop(api, "pub-ro")
    before = api.get("/api/escales/pledges", headers=ADMIN).json()
    for _ in range(3):
        api.get(URL)
    assert api.get("/api/escales/pledges", headers=ADMIN).json() == before
    for method in ("post", "put", "delete", "patch"):
        assert getattr(api, method)(URL).status_code == 405
