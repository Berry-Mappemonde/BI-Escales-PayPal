"""Round-3 tester fixes: dedup donations, PayPal return flow, referral 403, webhooks, email."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.project_onboarding.constants import (
    DEMO_PROJECT_ID,
    ONBOARDED_STATUS,
    ONBOARDING_HELD_STATUS,
    ONBOARDING_REQUIRED_STATUS,
)
from app.project_onboarding import store
from app.project_onboarding.email_template import render_onboarding_email
from app.project_onboarding.service import email_preview, handle_onboarding_return
from app.project_onboarding.store import reset_onboarding_store
from app.routers import project_onboarding as onboarding_router
from tests.test_project_onboarding import MockPayPal


@pytest.fixture
def onboarding_api(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ONBOARD_AFTER_PAYMENT_ENABLED", "1")
    monkeypatch.setenv("ESCALES_DEMO_PROJECT_CONTACT_EMAIL", "project@example.com")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "cid")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "secret")
    monkeypatch.setenv("ESCALES_WEBHOOKS_ENABLED", "1")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "wh-mock")
    reset_onboarding_store()
    app = FastAPI()
    app.include_router(onboarding_router.router)
    app.include_router(onboarding_router.webhooks_router)
    with TestClient(app) as client:
        yield client
    reset_onboarding_store()


class MongoLikeCursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._rows):
            raise StopAsyncIteration
        row = self._rows[self._index]
        self._index += 1
        return row


class MongoLikeCollection:
    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}

    async def replace_one(self, _filter: dict, doc: dict, upsert: bool = True) -> None:
        _ = upsert
        _id = str(doc.get("_id") or "")
        if not _id:
            raise ValueError("_id required")
        self._rows[_id] = dict(doc)

    async def find_one(self, filt: dict) -> dict | None:
        if "_id" in filt:
            row = self._rows.get(str(filt["_id"]))
            return dict(row) if row else None
        for row in self._rows.values():
            if all(row.get(k) == v for k, v in filt.items()):
                return dict(row)
        return None

    def find(self, filt: dict) -> MongoLikeCursor:
        matches = [dict(row) for row in self._rows.values() if all(row.get(k) == v for k, v in filt.items())]
        return MongoLikeCursor(matches)


@pytest.fixture
def mongo_like_store(monkeypatch):
    coll = MongoLikeCollection()
    monkeypatch.setattr(store, "_mongo_wanted", lambda: True)

    async def _coll():
        return coll

    monkeypatch.setattr(store, "_collection", _coll)
    reset_onboarding_store()
    yield coll
    reset_onboarding_store()


def test_list_donations_single_row_with_mongo_cache(mongo_like_store):
    async def _run() -> None:
        did = "donation-dedup-1"
        await store.save_donation(
            {
                "_id": did,
                "project_id": DEMO_PROJECT_ID,
                "amount_eur": "9.00",
                "created_at": "2026-11-09T12:00:00Z",
            }
        )
        rows = await store.list_donations(DEMO_PROJECT_ID)
        assert len(rows) == 1
        assert rows[0]["_id"] == did
        rows_again = await store.list_donations(DEMO_PROJECT_ID)
        assert len(rows_again) == 1

    asyncio.run(_run())


def test_donation_survives_partner_referral_403(onboarding_api, monkeypatch):
    onboarding_api.post("/api/escales/project-onboarding/seed", headers={"x-admin-key": "test-admin"})
    mock = MockPayPal(fail_referral_status=403)
    monkeypatch.setattr("app.project_onboarding.service._paypal", lambda: mock)
    res = onboarding_api.post(
        f"/api/escales/project-onboarding/projects/{DEMO_PROJECT_ID}/donations",
        json={"amount_eur": "15.00"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body.get("order_id") == "ORDER-MOCK"
    link = body.get("onboarding_link") or {}
    assert link.get("available") is False
    assert link.get("reason") == "partner_referrals_unavailable"
    assert link.get("http_status") == 403


def test_forged_return_ignored_without_partner_merchant_id(monkeypatch):
    store.reset_onboarding_store()
    pid = "proj-forge-no-partner"
    monkeypatch.delenv("PAYPAL_PARTNER_MERCHANT_ID", raising=False)

    async def _run() -> None:
        await store.save_project({"_id": pid, "demo_fake": True, "onboarding_status": "pending"})
        result = await handle_onboarding_return(
            pid,
            merchant_id_in_paypal="FORGED-MERCHANT-ID",
            permissions_granted=True,
            is_email_confirmed=True,
        )
        project = await store.get_project(pid)
        assert result["verified"] is False
        assert project["onboarding_status"] != ONBOARDED_STATUS

    asyncio.run(_run())


def test_forged_return_ignored_when_seller_status_negative(monkeypatch):
    store.reset_onboarding_store()
    pid = "proj-forge-seller"
    monkeypatch.setenv("PAYPAL_PARTNER_MERCHANT_ID", "PARTNER-MOCK")
    mock = MockPayPal(seller_receivable=False, seller_email_confirmed=False)
    monkeypatch.setattr("app.project_onboarding.service._paypal", lambda: mock)

    async def _run() -> None:
        await store.save_project({"_id": pid, "demo_fake": True, "onboarding_status": "pending"})
        result = await handle_onboarding_return(
            pid,
            merchant_id_in_paypal="FORGED-MERCHANT-ID",
            permissions_granted=True,
            is_email_confirmed=True,
            client=mock,
        )
        project = await store.get_project(pid)
        assert result["verified"] is False
        assert project["onboarding_status"] != ONBOARDED_STATUS

    asyncio.run(_run())


def test_merchant_webhook_rejects_failed_verification(onboarding_api, monkeypatch):
    onboarding_api.post("/api/escales/project-onboarding/seed", headers={"x-admin-key": "test-admin"})

    class FailVerifyPayPal(MockPayPal):
        def verify_webhook_signature(self, **kwargs):
            return {"verification_status": "FAILURE"}

    monkeypatch.setattr("app.routers.project_onboarding._paypal_client", lambda: FailVerifyPayPal())
    payload = {
        "id": "WH-EVENT-FAIL",
        "event_type": "MERCHANT.ONBOARDING.COMPLETED",
        "resource": {"tracking_id": DEMO_PROJECT_ID},
    }
    headers = {
        "PAYPAL-TRANSMISSION-ID": "tx-fail",
        "PAYPAL-TRANSMISSION-TIME": "2026-11-09T00:00:00Z",
        "PAYPAL-TRANSMISSION-SIG": "c2ln",
        "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT",
        "PAYPAL-AUTH-ALGO": "SHA256withRSA",
    }
    res = onboarding_api.post(
        "/api/escales/project-onboarding/webhooks/paypal-merchant",
        headers=headers,
        content=json.dumps(payload),
    )
    assert res.status_code == 401


def test_en_email_uses_english_foundation_name():
    project = {
        "title_en": "Demo Project",
        "title_fr": "Projet Démo",
        "foundation_title_en": "Fictional Ocean Foundation (fictional / sandbox)",
        "foundation_title_fr": "Fondation Fictive des Océans (fictif / sandbox)",
    }
    from app.project_onboarding.service import _localized

    loc = _localized(project, "en")
    rendered = render_onboarding_email(
        lang="en",
        amount_eur="10.00",
        foundation_name=loc["foundation_title"],
        project_title=loc["title"],
        action_url="https://www.sandbox.paypal.com/example",
        donation_status=ONBOARDING_HELD_STATUS,
        deadline_iso="2026-12-10T12:00:00Z",
    )
    assert "Fictional Ocean Foundation" in rendered["html"]
    assert "Fondation Fictive" not in rendered["html"]


def test_onboarding_required_email_no_held_wording():
    rendered = render_onboarding_email(
        lang="en",
        amount_eur="12.00",
        foundation_name="Fictional Ocean Foundation",
        project_title="Demo Project",
        action_url="https://www.sandbox.paypal.com/example",
        donation_status=ONBOARDING_REQUIRED_STATUS,
        deadline_iso=None,
    )
    assert "before the donation can be paid" in rendered["html"]
    assert "held for 30 days" not in rendered["html"].lower()
    rendered_fr = render_onboarding_email(
        lang="fr",
        amount_eur="12.00",
        foundation_name="Fondation Fictive",
        project_title="Projet",
        action_url="https://www.sandbox.paypal.com/example",
        donation_status=ONBOARDING_REQUIRED_STATUS,
        deadline_iso=None,
    )
    assert "avant que le don puisse être payé" in rendered_fr["html"]
    assert "retenus 30 jours" not in rendered_fr["html"].lower()


def test_project_onboarding_api_route_snapshot():
    from importlib import reload
    from app.routers import project_onboarding as mod

    reload(mod)
    snapshot = (Path(__file__).parent / "fixtures" / "project_onboarding_api_routes.snapshot.txt").read_text(
        encoding="utf-8"
    )
    expected = sorted(line.strip() for line in snapshot.splitlines() if line.strip())

    def collect(router) -> list[str]:
        rows: list[str] = []
        for route in router.routes:
            methods = sorted(getattr(route, "methods", None) or [])
            if not methods:
                continue
            rows.append(f"{methods[0]} {route.path}")
        return sorted(rows)

    actual = sorted(collect(mod.router) + collect(mod.webhooks_router))
    assert actual == expected
    assert len(actual) == 11
