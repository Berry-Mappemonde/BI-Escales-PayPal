"""Default Vault callback URLs and departure-day charge for vaulted pledges."""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.config import public_base_url, vault_cancel_url, vault_return_url
from app.escales.departure_clock import run_departure_clock
from app.escales.ledger import get_ledger
from app.escales.pledges import create_pledge, register_vault_pledge


def test_vault_urls_default_to_public_service(monkeypatch):
    monkeypatch.delenv("ESCALES_VAULT_RETURN_URL", raising=False)
    monkeypatch.delenv("ESCALES_VAULT_CANCEL_URL", raising=False)
    monkeypatch.setenv("ESCALES_PUBLIC_URL", "https://bi-escales-api.onrender.com")
    base = public_base_url()
    assert vault_return_url() == f"{base}/?vault=return"
    assert vault_cancel_url() == f"{base}/?vault=cancel"


class _VaultClockFake:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def create_setup_token(self, return_url: str, cancel_url: str, **kwargs) -> dict:
        self.calls.append(("setup", return_url, cancel_url))
        return {"id": "SETUP1", "links": [{"rel": "approve", "href": "https://sandbox.paypal.com/setup"}]}

    def create_payment_token(self, setup_token_id: str, **kwargs) -> dict:
        self.calls.append(("payment_token", setup_token_id, kwargs))
        return {"id": "VAULT-1", "payment_source": {"paypal": {}}}

    def get_setup_token(self, setup_token_id: str) -> dict:
        return {"id": setup_token_id, "status": "APPROVED"}

    def charge_vaulted(self, vault_id, amount_eur, reference_id, source="paypal", **kwargs):
        self.calls.append(("charge_vaulted", vault_id, amount_eur, reference_id, source))
        return {"id": "ORD1", "status": "COMPLETED", "purchase_units": [{"payments": {"captures": [{"id": "CAP1", "status": "COMPLETED"}]}}]}

    def delete_payment_token(self, vault_id):
        self.calls.append(("delete_token", vault_id))
        return {}


def test_departure_clock_charges_vaulted_pledge_on_departure_day(monkeypatch):
    monkeypatch.setenv("ESCALES_VAULT_ENABLED", "1")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-20T12:00:00Z")
    departure = "2026-11-20T08:00:00+00:00"
    fake = _VaultClockFake()

    async def body():
        await get_ledger().ensure_milestone(
            "dep-test-vault",
            meta={"capture_on": "departure", "departure_iso": departure},
        )
        created = await create_pledge(
            amount_eur="12.00",
            description="vault depart",
            milestone_id="dep-test-vault",
            client=fake,
            payment_mode="VAULT",
        )
        vaulted = await register_vault_pledge(created["_id"], fake)
        assert vaulted["status"] == "vaulted"
        result = await run_departure_clock(fake)
        assert result["actions"] == [{"pledge_id": created["_id"], "action": "capture"}]
        stored = await get_ledger().get_pledge(created["_id"])
        assert stored["status"] == "captured"
        assert stored["captured_at"] == "2026-11-20T12:00:00+00:00"
        assert ("charge_vaulted", "VAULT-1", "12.00", created["_id"], "paypal") in fake.calls
        assert ("delete_token", "VAULT-1") in fake.calls
        assert stored.get("vault_token_deleted") is True

    asyncio.run(body())


def test_far_departure_falls_back_to_vault_when_enabled(monkeypatch):
    monkeypatch.setenv("ESCALES_VAULT_ENABLED", "1")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-10-01T08:00:00Z")
    fake = _VaultClockFake()

    async def body():
        await get_ledger().ensure_milestone(
            "dep-far-vault",
            meta={"capture_on": "departure", "departure_iso": "2026-11-20T08:00:00+00:00"},
        )
        created = await create_pledge(
            amount_eur="5.00",
            description="trop tot mais vault",
            milestone_id="dep-far-vault",
            client=fake,
        )
        assert created["payment_mode"] == "VAULT"
        assert any(call[0] == "setup" for call in fake.calls)

    asyncio.run(body())
