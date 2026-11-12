"""One approval policy before immediate card capture and held-card authorization."""
import asyncio

import pytest

from app.escales.ledger import reset_ledger
from app.escales.paypal_client import PayPalError
from app.escales.pledges import authorize_pledge, create_pledge, require_pledge
from tests.test_escales_pledges import Spy


class CardOrderSpy(Spy):
    def create_card_authorize_order(self, **kwargs):
        return self.create_authorize_order(
            kwargs["amount_eur"], kwargs["description"], kwargs["reference_id"],
            idempotency_key=kwargs.get("idempotency_key"),
        )


@pytest.mark.parametrize("kind", ["common_fund", "project_pledge", "stop_gift"])
@pytest.mark.parametrize("order_status,auth,allowed", [
    pytest.param("APPROVED", None, True, id="approved-without-3ds"),
    pytest.param("APPROVED", {}, True, id="empty-authentication-result"),
    pytest.param("APPROVED", {"liability_shift": "POSSIBLE", "three_d_secure": {
        "enrollment_status": "Y", "authentication_status": "Y",
    }}, True, id="successful-3ds"),
    pytest.param("APPROVED", {"liability_shift": "NO", "three_d_secure": {
        "enrollment_status": "N",
    }}, True, id="negative-enrollment"),
    pytest.param("APPROVED", {"liability_shift": "POSSIBLE", "three_d_secure": {
        "enrollment_status": "R",
    }}, False, id="rejected-enrollment"),
    pytest.param("APPROVED", {"liability_shift": "POSSIBLE", "three_d_secure": {
        "enrollment_status": "Y", "authentication_status": "N",
    }}, False, id="failed-authentication"),
    pytest.param("APPROVED", {"liability_shift": "POSSIBLE", "three_d_secure": {
        "enrollment_status": "Y", "authentication_status": "R",
    }}, False, id="rejected-authentication"),
    pytest.param("APPROVED", {"liability_shift": "NO", "three_d_secure": {
        "enrollment_status": "Y", "authentication_status": "A",
    }}, False, id="attempted-without-liability-shift"),
    pytest.param("APPROVED", {"liability_shift": "UNKNOWN", "three_d_secure": {
        "enrollment_status": "Y", "authentication_status": "C",
    }}, False, id="attempted-with-unknown-liability"),
    pytest.param("APPROVED", {"liability_shift": "UNKNOWN"}, False, id="unknown-liability-without-3ds"),
    pytest.param("APPROVED", {"liability_shift": "YES", "three_d_secure": {
        "enrollment_status": "Y", "authentication_status": "Y",
    }}, True, id="liability-yes"),
    pytest.param("CREATED", {"liability_shift": "POSSIBLE", "three_d_secure": {
        "enrollment_status": "Y", "authentication_status": "Y",
    }}, True, id="created-after-successful-3ds"),
    pytest.param("CREATED", {"liability_shift": "YES", "three_d_secure": {
        "enrollment_status": "Y", "authentication_status": "A",
    }}, True, id="created-after-attempted-3ds"),
    pytest.param("CREATED", None, False, id="created-without-3ds"),
    pytest.param("CREATED", {"liability_shift": "NO", "three_d_secure": {
        "enrollment_status": "Y", "authentication_status": "N",
    }}, False, id="created-failed-3ds"),
    pytest.param("CREATED", {"liability_shift": "NO", "three_d_secure": {
        "enrollment_status": "Y", "authentication_status": "R",
    }}, False, id="created-rejected-3ds"),
    pytest.param("DECLINED", None, False, id="declined-card"),
    pytest.param("PAYER_ACTION_REQUIRED", None, False, id="buyer-action-required"),
])
def test_card_approval_before_both_money_paths(monkeypatch, kind, order_status, auth, allowed):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_CARD_FIELDS_ENABLED", "1")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-12T08:00:00Z")

    class CardSpy(CardOrderSpy):
        def get_card_order(self, order_id):
            self.calls.append(("card.read", order_id))
            card = {"brand": "VISA", "last_digits": "0004"}
            if auth is not None:
                card["authentication_result"] = auth
            return {"id": order_id, "status": order_status, "payment_source": {"card": card}}

        def get_order(self, order_id):
            raise AssertionError("Cards must use the expanded server-side approval read")

    async def run():
        reset_ledger()
        client = CardSpy()
        created = await create_pledge(
            amount_eur="1.00", description="cursor-agent-test card approval",
            kind=kind, milestone_id="dep-la-rochelle" if kind == "stop_gift" else "",
            checkout_method="card", client=client,
        )
        if allowed:
            saved = await authorize_pledge(created["_id"], client)
            assert saved["status"] == ("authorized" if kind == "stop_gift" else "captured")
            writes = [call[0] for call in client.calls if call[0] in {"authorize", "orders.capture"}]
            assert writes == (["authorize"] if kind == "stop_gift" else ["orders.capture"])
        else:
            with pytest.raises(ValueError, match="not approved|authentication"):
                await authorize_pledge(created["_id"], client)
            assert (await require_pledge(created["_id"]))["status"] == "created"
            assert not any(call[0] in {"authorize", "orders.capture", "capture"} for call in client.calls)
        assert len([call for call in client.calls if call[0] == "card.read"]) == 1

    try:
        asyncio.run(run())
    finally:
        reset_ledger()


@pytest.mark.parametrize("kind", ["common_fund", "project_pledge", "stop_gift"])
def test_processor_decline_after_approval_never_records_payment(monkeypatch, kind):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_CARD_FIELDS_ENABLED", "1")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-11-12T08:00:00Z")

    class DeclinedCard(CardOrderSpy):
        def get_card_order(self, order_id):
            return {"id": order_id, "status": "APPROVED", "payment_source": {"card": {"last_digits": "0004"}}}

        def capture_order(self, *_args, **_kwargs):
            raise PayPalError(422, '{"details":[{"issue":"INSTRUMENT_DECLINED"}]}')

        def authorize_order(self, *_args, **_kwargs):
            raise PayPalError(422, '{"details":[{"issue":"INSTRUMENT_DECLINED"}]}')

    async def run():
        reset_ledger()
        client = DeclinedCard()
        pledge = await create_pledge(
            amount_eur="1.00", description="cursor-agent-test decline",
            kind=kind, milestone_id="dep-la-rochelle" if kind == "stop_gift" else "",
            checkout_method="card", client=client,
        )
        with pytest.raises(PayPalError):
            await authorize_pledge(pledge["_id"], client)
        saved = await require_pledge(pledge["_id"])
        assert saved["status"] not in {"captured", "authorized"}
        assert not saved.get("capture_id")
        assert not saved.get("authorization_id")

    try:
        asyncio.run(run())
    finally:
        reset_ledger()
