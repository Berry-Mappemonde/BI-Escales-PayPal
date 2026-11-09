"""Recover pledge authorization when PayPal returns ORDER_ALREADY_AUTHORIZED."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.ledger import get_ledger, list_finance_entries
from app.escales.paypal_client import PayPalError
from app.escales.pledges import authorize_pledge, create_pledge, reset_ledger


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-12T08:00:00Z")
    reset_ledger()

    async def seed():
        await get_ledger().ensure_milestone(
            "dep-la-rochelle",
            meta={
                "capture_on": "departure",
                "departure_iso": "2026-11-20T08:00:00+00:00",
            },
        )

    asyncio.run(seed())
    yield
    reset_ledger()


class RecoverSpy:
    def __init__(self, *, order_status: str = "APPROVED", get_order_body: dict | None = None):
        self.calls: list[tuple] = []
        self.n = 0
        self.order_status = order_status
        self.get_order_body = get_order_body
        self.authorize_raises: PayPalError | None = None

    def create_authorize_order(self, amount_eur, description, reference_id, idempotency_key=None):
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

    def authorize_order(self, order_id, **kwargs):
        self.calls.append(("authorize", order_id))
        if self.authorize_raises is not None:
            raise self.authorize_raises
        return {
            "id": order_id,
            "purchase_units": [{
                "payments": {
                    "authorizations": [{
                        "id": f"AUTH-{order_id}",
                        "expiration_time": "2099-01-01T00:00:00Z",
                    }],
                },
            }],
        }

    def get_order(self, order_id):
        self.calls.append(("orders.get", order_id))
        if self.get_order_body is not None:
            body = dict(self.get_order_body)
            body.setdefault("id", order_id)
            body.setdefault("status", self.order_status)
            return body
        return {"id": order_id, "status": self.order_status}


def _already_auth_exc() -> PayPalError:
    return PayPalError(
        422,
        {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "ORDER_ALREADY_AUTHORIZED"}]},
    )


def _adopted_order_body(
    pledge_id: str,
    *,
    amount: str = "20.00",
    currency: str = "EUR",
    custom_id: str | None = None,
    invoice_id: str | None = None,
    auth_id: str = "28L87826KG020904R",
    auth_status: str = "CREATED",
) -> dict:
    ref = custom_id if custom_id is not None else pledge_id[:127]
    invoice = invoice_id if invoice_id is not None else pledge_id[:127]
    return {
        "purchase_units": [{
            "custom_id": ref,
            "invoice_id": invoice,
            "payments": {
                "authorizations": [{
                    "id": auth_id,
                    "status": auth_status,
                    "expiration_time": "2099-06-01T00:00:00Z",
                    "amount": {"currency_code": currency, "value": amount},
                }],
            },
        }],
    }


def _finance_authorized(pledge_id: str, entries: list[dict]) -> list[dict]:
    return [
        row for row in entries
        if row.get("kind") == "pledge_authorized" and row.get("pledge_id") == pledge_id
    ]


def _authorize_call_count(spy: RecoverSpy) -> int:
    return sum(1 for kind, _ in spy.calls if kind == "authorize")


def test_order_already_authorized_recovers_pledge():
    async def body():
        created = await create_pledge(
            amount_eur="20.00",
            description="20 milles",
            milestone_id="dep-la-rochelle",
            client=RecoverSpy(),
            client_key="recover-1",
        )
        spy = RecoverSpy(get_order_body=_adopted_order_body(created["_id"], amount="20.00"))
        spy.authorize_raises = _already_auth_exc()
        saved = await authorize_pledge(created["_id"], spy)
        assert saved["status"] == "authorized"
        assert saved["authorization_id"] == "28L87826KG020904R"
        entries = await list_finance_entries()
        assert len(_finance_authorized(created["_id"], entries)) == 1
        assert _authorize_call_count(spy) == 1
        assert ("authorize", created["order_id"]) in spy.calls
        assert ("orders.get", created["order_id"]) in spy.calls

    asyncio.run(body())


def test_repeat_authorize_is_noop_without_duplicate_finance():
    async def body():
        created = await create_pledge(
            amount_eur="15.00",
            description="miles",
            milestone_id="dep-la-rochelle",
            client=RecoverSpy(),
            client_key="recover-2",
        )
        spy = RecoverSpy(
            get_order_body=_adopted_order_body(
                created["_id"],
                amount="15.00",
                auth_id="AUTH-RECOVER-NOOP",
                auth_status="PENDING",
            ),
        )
        spy.authorize_raises = _already_auth_exc()
        first = await authorize_pledge(created["_id"], spy)
        calls_after_first = len(spy.calls)
        auth_id = first["authorization_id"]
        second = await authorize_pledge(created["_id"], spy)
        assert second["status"] == "authorized"
        assert second["authorization_id"] == auth_id == "AUTH-RECOVER-NOOP"
        assert len(spy.calls) == calls_after_first
        assert _authorize_call_count(spy) == 1
        entries = await list_finance_entries()
        assert len(_finance_authorized(created["_id"], entries)) == 1

    asyncio.run(body())


def test_other_422_issue_still_raises():
    async def body():
        spy = RecoverSpy()
        spy.authorize_raises = PayPalError(
            422,
            {"details": [{"issue": "INSTRUMENT_DECLINED"}]},
        )
        created = await create_pledge(
            amount_eur="10.00",
            description="miles",
            milestone_id="dep-la-rochelle",
            client=spy,
            client_key="recover-3",
        )
        with pytest.raises(PayPalError) as caught:
            await authorize_pledge(created["_id"], spy)
        assert caught.value.status == 422
        stored = await get_ledger().get_pledge(created["_id"])
        assert stored is not None
        assert stored["status"] == "created"
        entries = await list_finance_entries()
        assert len(_finance_authorized(created["_id"], entries)) == 0

    asyncio.run(body())


def test_order_already_authorized_without_usable_auth_still_raises():
    async def body():
        spy = RecoverSpy(
            get_order_body={
                "purchase_units": [{
                    "payments": {
                        "authorizations": [{
                            "id": "VOIDED-ONLY",
                            "status": "VOIDED",
                        }],
                    },
                }],
            },
        )
        original = _already_auth_exc()
        spy.authorize_raises = original
        created = await create_pledge(
            amount_eur="12.00",
            description="miles",
            milestone_id="dep-la-rochelle",
            client=spy,
            client_key="recover-4",
        )
        with pytest.raises(PayPalError) as caught:
            await authorize_pledge(created["_id"], spy)
        assert caught.value is original
        assert caught.value.status == 422
        stored = await get_ledger().get_pledge(created["_id"])
        assert stored is not None
        assert stored["status"] == "created"
        assert len(_finance_authorized(created["_id"], await list_finance_entries())) == 0

    asyncio.run(body())


@pytest.mark.parametrize(
    "field_kwargs",
    [
        {"amount": "99.00"},
        {"currency": "USD"},
        {"custom_id": "wrong-custom"},
        {"invoice_id": "wrong-invoice"},
    ],
    ids=["amount", "currency", "custom_id", "invoice_id"],
)
def test_adopted_authorization_mismatch_keeps_422(field_kwargs):
    async def body():
        created = await create_pledge(
            amount_eur="20.00",
            description="miles",
            milestone_id="dep-la-rochelle",
            client=RecoverSpy(),
            client_key=f"recover-mismatch-{field_kwargs}",
        )
        body_overrides = {"amount": "20.00", **field_kwargs}
        spy = RecoverSpy(get_order_body=_adopted_order_body(created["_id"], **body_overrides))
        original = _already_auth_exc()
        spy.authorize_raises = original
        with pytest.raises(PayPalError) as caught:
            await authorize_pledge(created["_id"], spy)
        assert caught.value is original
        assert caught.value.status == 422
        stored = await get_ledger().get_pledge(created["_id"])
        assert stored is not None
        assert stored["status"] == "created"
        assert stored.get("authorization_id") in (None, "")
        assert len(_finance_authorized(created["_id"], await list_finance_entries())) == 0

    asyncio.run(body())


def test_concurrent_authorize_one_paypal_call_one_ledger_row():
    async def body():
        holder = RecoverSpy()
        created = await create_pledge(
            amount_eur="25.00",
            description="miles",
            milestone_id="dep-la-rochelle",
            client=holder,
            client_key="recover-concurrent",
        )
        spy = RecoverSpy()
        first, second = await asyncio.gather(
            authorize_pledge(created["_id"], spy),
            authorize_pledge(created["_id"], spy),
        )
        auth_id = first["authorization_id"]
        assert first["status"] == "authorized"
        assert second["status"] == "authorized"
        assert second["authorization_id"] == auth_id
        assert auth_id == f"AUTH-{created['order_id']}"
        assert _authorize_call_count(spy) == 1
        entries = await list_finance_entries()
        assert len(_finance_authorized(created["_id"], entries)) == 1

    asyncio.run(body())
