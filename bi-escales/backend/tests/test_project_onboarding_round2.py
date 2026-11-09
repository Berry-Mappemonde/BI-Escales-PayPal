"""Round-2 fixes: email allowlist fail-closed, mongo _id uniqueness, return URL trust."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.project_onboarding.constants import DEMO_PROJECT_ID, ONBOARDED_STATUS
from app.project_onboarding.email_provider import allowlist_allows, send_html_email
from app.project_onboarding import store
from app.project_onboarding.service import handle_onboarding_return


class DuplicateKeyError(Exception):
    pass


class MongoLikeCollection:
    """Enforces unique _id like MongoDB (E11000 on collision)."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}

    async def replace_one(self, _filter: dict, doc: dict, upsert: bool = True) -> None:
        _ = upsert
        _id = str(doc.get("_id") or "")
        if not _id:
            raise ValueError("_id required")
        if _id in self._rows and self._rows[_id].get("kind") != doc.get("kind"):
            raise DuplicateKeyError(f"duplicate key {_id}")
        self._rows[_id] = dict(doc)

    async def find_one(self, filt: dict) -> dict | None:
        if "_id" in filt:
            row = self._rows.get(str(filt["_id"]))
            return dict(row) if row else None
        for row in self._rows.values():
            if all(row.get(k) == v for k, v in filt.items()):
                return dict(row)
        return None

    async def insert_one(self, doc: dict) -> None:
        _id = str(doc.get("_id") or "")
        if _id in self._rows:
            raise DuplicateKeyError(_id)
        self._rows[_id] = dict(doc)


@pytest.fixture
def mongo_like_store(monkeypatch):
    coll = MongoLikeCollection()
    monkeypatch.setattr(store, "_mongo_wanted", lambda: True)
    async def _coll():
        return coll
    monkeypatch.setattr(store, "_collection", _coll)
    store.reset_onboarding_store()
    yield coll
    store.reset_onboarding_store()


def test_allowlist_unset_blocks_recipient(monkeypatch):
    monkeypatch.delenv("ESCALES_EMAIL_ALLOWLIST", raising=False)
    assert allowlist_allows("project@example.com") is False


def test_allowlist_empty_blocks_recipient(monkeypatch):
    monkeypatch.setenv("ESCALES_EMAIL_ALLOWLIST", "")
    assert allowlist_allows("project@example.com") is False


def test_allowlist_rejects_unknown_domain(monkeypatch):
    monkeypatch.setenv("ESCALES_EMAIL_ALLOWLIST", "example.com")
    assert allowlist_allows("user@other.com") is False
    assert allowlist_allows("user@example.com") is True


def test_allowlist_removal_would_fail_this_test(monkeypatch):
    """If allowlist_allows() returns True when unset, this test must fail."""
    monkeypatch.delenv("ESCALES_EMAIL_ALLOWLIST", raising=False)
    assert allowlist_allows("anyone@anywhere.test") is False


def test_send_html_email_blocked_without_allowlist(monkeypatch):
    monkeypatch.setenv("ESCALES_EMAIL_ENABLED", "1")
    monkeypatch.setenv("ESCALES_EMAIL_API_URL", "https://email.example/send")
    monkeypatch.setenv("ESCALES_EMAIL_API_TOKEN", "token")
    monkeypatch.delenv("ESCALES_EMAIL_ALLOWLIST", raising=False)
    out = asyncio.run(send_html_email(to="project@example.com", subject="s", html="<p>x</p>"))
    assert out["sent"] is False
    assert out["reason"] == "allowlist"


def test_mongo_project_and_referral_both_persist(mongo_like_store):
    pid = DEMO_PROJECT_ID

    async def _run():
        await store.save_project({"_id": pid, "demo_fake": True, "title_fr": "t"})
        await store.save_referral({"project_id": pid, "action_url": "https://sandbox.paypal.example/link"})
        project = await store.get_project(pid)
        referral = await store.get_referral(pid)
        assert project is not None
        assert referral is not None
        assert project["_id"] == pid
        assert referral["project_id"] == pid
        assert mongo_like_store._rows[f"referral:{pid}"]["_id"] == f"referral:{pid}"

    asyncio.run(_run())


def test_forged_merchant_query_does_not_onboard(monkeypatch):
    store.reset_onboarding_store()
    pid = "proj-forge-test"
    monkeypatch.setenv("PAYPAL_PARTNER_MERCHANT_ID", "PARTNER-MOCK")

    class PayPalNoOnboard:
        def _req(self, method, path, json=None, **kwargs):
            if "merchant-integrations" in path:
                if "tracking_id=" in path:
                    return {"merchant_id": "MERCH-NO", "tracking_id": pid, "links": []}
                if "/merchant-integrations/" in path:
                    return {
                        "merchant_id": "MERCH-NO",
                        "payments_receivable": False,
                        "primary_email_confirmed": False,
                    }
            return {}

    async def _run():
        await store.save_project({"_id": pid, "demo_fake": True, "onboarding_status": "pending"})
        result = await handle_onboarding_return(
            pid,
            merchant_id_in_paypal="FORGED-MERCHANT-ID",
            permissions_granted=True,
            is_email_confirmed=True,
            client=PayPalNoOnboard(),  # type: ignore[arg-type]
        )
        project = await store.get_project(pid)
        assert result["verified"] is False
        assert project["onboarding_status"] != ONBOARDED_STATUS

    asyncio.run(_run())
