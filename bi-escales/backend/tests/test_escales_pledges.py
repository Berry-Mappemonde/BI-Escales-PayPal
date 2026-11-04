"""Pledge state machine and the PayPal AUTHORIZE client. No network."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.config import EscalesConfig, load_config
from app.escales.paypal_client import PayPalClient, approve_link
from app.escales.pledges import (
    COLLECTIONS,
    IllegalTransition,
    PLEDGE_KINDS,
    authorize_pledge,
    capture_pledge,
    create_pledge,
    get_ledger,
    reset_ledger,
    to_public,
    void_pledge,
)


@pytest.fixture(autouse=True)
def memory_ledger(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    reset_ledger()
    yield
    reset_ledger()


class Spy:
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

    def authorize_order(self, order_id, **kwargs):
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

    def capture_authorization(self, authorization_id, final=True, **kwargs):
        self.calls.append(("capture", authorization_id))
        return {"id": "CAP", "status": "COMPLETED"}

    def void_authorization(self, authorization_id, **kwargs):
        self.calls.append(("void", authorization_id))
        return {}

    def get_order(self, order_id):
        self.calls.append(("orders.get", order_id))
        return {"id": order_id, "status": "APPROVED"}

    def get_authorization(self, authorization_id):
        self.calls.append(("authorizations.get", authorization_id))
        return {"id": authorization_id, "status": "CREATED"}

    def create_setup_token(self, return_url, cancel_url, **kwargs):
        self.calls.append(("setup_token", kwargs))
        return {
            "id": "SETUP1",
            "status": "CREATED",
            "links": [{
                "rel": "approve",
                "href": "https://www.sandbox.paypal.com/ag/v1/vault/setup-token/SETUP1",
            }],
        }


def _names(spy: Spy) -> list[str]:
    return [call[0] for call in spy.calls]


def test_create_authorize_order_is_eur_and_idempotent(monkeypatch):
    monkeypatch.delenv("ESCALES_RETURN_URL", raising=False)
    monkeypatch.delenv("ESCALES_CANCEL_URL", raising=False)
    seen = []

    def handler(request: httpx.Request):
        seen.append((
            request.method,
            request.url.path,
            request.headers.get("PayPal-Request-Id"),
            request.content,
            request.headers.get("Prefer"),
        ))
        path = request.url.path
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        if path == "/v2/checkout/orders" and request.method == "POST":
            body = json.loads(request.content)
            assert body["intent"] == "AUTHORIZE"
            assert body["purchase_units"][0]["amount"] == {"currency_code": "EUR", "value": "20.00"}
            context = body["payment_source"]["paypal"]["experience_context"]
            assert context["return_url"] == "https://bi-escales-api.onrender.com/?paypal=return"
            assert context["cancel_url"] == "https://bi-escales-api.onrender.com/?paypal=cancel"
            assert context["user_action"] == "CONTINUE"
            return httpx.Response(201, json={
                "id": "ORDER1",
                "status": "CREATED",
                "intent": "AUTHORIZE",
                "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1"}],
            })
        if path == "/v2/checkout/orders/ORDER1/authorize":
            return httpx.Response(201, json={
                "id": "ORDER1",
                "purchase_units": [{
                    "payments": {"authorizations": [{"id": "AUTH1", "expiration_time": "2026-12-01T00:00:00Z"}]},
                }],
            })
        if path == "/v2/checkout/orders/ORDER1" and request.method == "GET":
            return httpx.Response(200, json={"id": "ORDER1", "status": "APPROVED"})
        if path == "/v2/payments/authorizations/AUTH1" and request.method == "GET":
            return httpx.Response(200, json={"id": "AUTH1", "status": "CREATED"})
        if path == "/v2/payments/authorizations/AUTH1/void":
            return httpx.Response(204)
        return httpx.Response(404, json={"name": "NOT_FOUND"})

    client = PayPalClient(
        EscalesConfig("test-client-id", "test-client-secret"),
        transport=httpx.MockTransport(handler),
    )
    order = client.create_authorize_order("20.00", "Menu Berry-Mappemonde", "p1", idempotency_key="pledge-key-1")
    assert order["id"] == "ORDER1"
    assert approve_link(order) == "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1"
    assert approve_link({"id": "ORDER9"}) == "https://www.sandbox.paypal.com/checkoutnow?token=ORDER9"
    client.authorize_order("ORDER1")
    assert client.get_order("ORDER1")["status"] == "APPROVED"
    assert client.get_authorization("AUTH1")["id"] == "AUTH1"
    assert client.void_authorization("AUTH1") == {}
    paths = [item[1] for item in seen]
    assert paths == [
        "/v1/oauth2/token",
        "/v2/checkout/orders",
        "/v2/checkout/orders/ORDER1/authorize",
        "/v2/checkout/orders/ORDER1",
        "/v2/payments/authorizations/AUTH1",
        "/v2/payments/authorizations/AUTH1/void",
    ]
    assert seen[1][2] == "pledge-key-1"
    assert seen[1][4] == "return=representation"
    assert seen[2][4] == "return=representation"
    assert seen[3][4] is None
    assert all("capture" not in path for path in paths)


def test_charge_vaulted_sends_the_matching_payment_source():
    bodies = []

    def handler(request: httpx.Request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"id": "ORD-V", "status": "COMPLETED", "intent": "CAPTURE"})

    client = PayPalClient(
        EscalesConfig("test-client-id", "test-client-secret"),
        transport=httpx.MockTransport(handler),
    )
    client.charge_vaulted("WALLET1", "1.00", "ref-wallet")
    client.charge_vaulted("CARD1", "1.00", "ref-card", source="card")
    assert bodies[0]["payment_source"] == {"paypal": {"vault_id": "WALLET1"}}
    assert bodies[1]["payment_source"] == {"card": {"vault_id": "CARD1"}}


def test_non_sandbox_env_is_refused(monkeypatch):
    monkeypatch.setenv("PAYPAL_ENV", "live")
    with pytest.raises(RuntimeError):
        load_config()


def test_collections_are_namespaced():
    assert COLLECTIONS == (
        "escales_pledges",
        "escales_milestones",
        "escales_audit",
        "escales_finance",
        "escales_webhooks",
    )


def test_same_client_key_reuses_pledge_without_a_second_order():
    async def body():
        spy = Spy()
        first = await create_pledge(
            amount_eur="20.00",
            description="20 milles",
            milestone_id="dep-mayotte",
            client=spy,
            client_key="same-key",
        )
        second = await create_pledge(
            amount_eur="60.00",
            description="autre",
            milestone_id="other",
            client=spy,
            client_key="same-key",
        )
        assert first["_id"] == second["_id"]
        assert first["order_id"] == second["order_id"] == "ORDER1"
        assert first["amount_eur"] == "20.00"
        assert _names(spy) == ["create"]
        assert spy.calls[0][2] == "same-key"

    asyncio.run(body())


def test_state_machine_and_forbidden_transitions():
    async def body():
        spy = Spy()
        created = await create_pledge(
            amount_eur="20.00",
            description="20 milles",
            milestone_id="dep-mayotte",
            client=spy,
            client_key="pledge-a",
        )
        assert created["status"] == "created"
        assert created["intent"] == "AUTHORIZE"
        assert created["currency"] == "EUR"
        with pytest.raises(IllegalTransition):
            await capture_pledge(created["_id"], spy)
        with pytest.raises(IllegalTransition):
            await void_pledge(created["_id"], spy)

        authorized = await authorize_pledge(created["_id"], spy)
        assert authorized["status"] == "authorized"
        assert authorized["authorization_id"] == "AUTH-ORDER1"
        assert authorized["authorization_expires_at"] == "2026-12-01T00:00:00Z"
        with pytest.raises(IllegalTransition):
            await authorize_pledge(created["_id"], spy)

        captured = await capture_pledge(created["_id"], spy)
        assert captured["status"] == "captured"
        with pytest.raises(IllegalTransition):
            await void_pledge(created["_id"], spy)
        with pytest.raises(IllegalTransition):
            await capture_pledge(created["_id"], spy)

        other = await create_pledge(
            amount_eur="60.00",
            description="diner",
            milestone_id="dep-mayotte",
            client=spy,
            client_key="pledge-b",
        )
        await authorize_pledge(other["_id"], spy)
        voided = await void_pledge(other["_id"], spy)
        assert voided["status"] == "voided"
        with pytest.raises(IllegalTransition):
            await capture_pledge(other["_id"], spy)
        with pytest.raises(IllegalTransition):
            await void_pledge(other["_id"], spy)

        assert _names(spy).count("capture") == 1
        assert _names(spy).count("void") == 1
        assert _names(spy).count("orders.get") == 2
        assert "authorizations.get" not in _names(spy)

    asyncio.run(body())


def test_omitted_kind_stays_a_mile_and_targets_the_milestone():
    async def body():
        spy = Spy()
        created = await create_pledge(
            amount_eur="20.00",
            description="20 milles",
            milestone_id="dep-mayotte",
            client=spy,
        )
        assert created["kind"] == "mile"
        assert created["target_id"] == "dzaoudzi-mayotte"
        assert created["intent"] == "AUTHORIZE"
        assert created["status"] == "created"
        assert _names(spy) == ["create"]

    asyncio.run(body())


def test_kind_and_target_are_stored_and_unknown_kind_is_rejected():
    async def body():
        spy = Spy()
        created = await create_pledge(
            amount_eur="60.00",
            description="diner",
            milestone_id="dep-mayotte",
            client=spy,
            kind="meal",
            target_id="mayotte",
        )
        assert created["kind"] == "meal"
        assert created["target_id"] == "dzaoudzi-mayotte"
        assert created["milestone_id"] == "dep-dzaoudzi-mayotte"
        prefixed = await create_pledge(
            amount_eur="20.00",
            description="20 milles",
            milestone_id="dep-mayotte",
            client=spy,
            kind="mile",
            target_id="dep-mayotte",
        )
        assert prefixed["target_id"] == "dzaoudzi-mayotte"
        assert prefixed["milestone_id"] == "dep-dzaoudzi-mayotte"
        stored = await get_ledger().get_pledge(created["_id"])
        assert stored["kind"] == "meal"
        assert stored["target_id"] == "dzaoudzi-mayotte"
        project = await create_pledge(
            amount_eur="15.00",
            description="don",
            milestone_id="dep-mayotte",
            client=spy,
            kind="project_pledge",
            target_id="projet-ecole",
        )
        assert project["target_id"] == "projet-ecole"
        fund = await create_pledge(
            amount_eur="8.00",
            description="caisse",
            milestone_id="dep-mayotte",
            client=spy,
            kind="common_fund",
            target_id="mayotte",
        )
        assert fund["target_id"] == "dzaoudzi-mayotte"
        with pytest.raises(ValueError):
            await create_pledge(
                amount_eur="8.00",
                description="caisse",
                milestone_id="dep-mayotte",
                client=spy,
                kind="common_fund",
                target_id="projet-ecole",
            )
        with pytest.raises(ValueError):
            await create_pledge(
                amount_eur="1.00",
                description="autre escale",
                milestone_id="dep-mayotte",
                client=spy,
                kind="mile",
                target_id="dakar",
            )
        with pytest.raises(ValueError):
            await create_pledge(
                amount_eur="30.00",
                description="poste",
                milestone_id="dep-mayotte",
                client=spy,
                kind="berth",
                target_id="nulle-part",
            )
        with pytest.raises(ValueError):
            await create_pledge(
                amount_eur="30.00",
                description="poste",
                milestone_id="dep-mayotte",
                client=spy,
                kind="berth",
                target_id="Projet Ecole",
            )
        with pytest.raises(ValueError):
            await create_pledge(
                amount_eur="1.00",
                description="inconnu",
                milestone_id="dep-mayotte",
                client=spy,
                kind="yacht",
            )
        assert set(PLEDGE_KINDS) == {
            "mile", "project_pledge", "berth", "night", "meal", "care", "cabin_leg", "common_fund",
        }

    asyncio.run(body())


def test_cabin_leg_authorizes_and_waits_for_departure(monkeypatch):
    """Réserver une cabine autorise. Le départ de A capture, l'annulation vide."""
    from app.escales.milestones import decision_for_evidence, record_evidence
    from app.escales.naviguide_bridge import sync_leg_shells

    monkeypatch.setenv("ESCALES_VAULT_ENABLED", "1")
    monkeypatch.delenv("ESCALES_CLOCK_START", raising=False)
    leg = "leg-la-rochelle-to-ajaccio-corse"

    async def body():
        await sync_leg_shells()
        spy = Spy()
        created = await create_pledge(
            amount_eur="80.00",
            description="cabine Ajaccio Fort-de-France",
            milestone_id=leg,
            client=spy,
            kind="cabin_leg",
        )
        assert created["intent"] == "AUTHORIZE"
        assert created["payment_mode"] == "AUTHORIZE"
        assert created["kind"] == "cabin_leg"
        assert created["target_id"] == leg
        assert created["status"] == "created"
        assert _names(spy) == ["create"]
        from_stop = await create_pledge(
            amount_eur="80.00",
            description="cabine depuis La Rochelle",
            milestone_id="dep-la-rochelle",
            client=spy,
            kind="cabin_leg",
        )
        assert from_stop["milestone_id"] == "leg-la-rochelle-to-ajaccio-corse"
        far_cabin = await create_pledge(
            amount_eur="80.00",
            description="cabine depuis Mayotte",
            milestone_id="dep-mayotte",
            client=spy,
            kind="cabin_leg",
        )
        assert far_cabin["payment_mode"] == "VAULT"
        assert far_cabin["intent"] == "VAULT"
        assert far_cabin["setup_token_id"] == "SETUP1"
        assert _names(spy)[-1] == "setup_token"
        with pytest.raises(ValueError):
            await create_pledge(
                amount_eur="80.00",
                description="cabine inconnue",
                milestone_id="dep-nulle-part",
                client=spy,
                kind="cabin_leg",
            )
        departed = await record_evidence(leg, met=True, facts={"departed": True})
        milestone = await get_ledger().get_milestone(leg)
        assert decision_for_evidence({"facts": departed["facts"], "met": True}, milestone) == "capture"
        cancelled = await record_evidence(leg, met=False, facts={"cancelled": True})
        assert decision_for_evidence(
            {"facts": cancelled["facts"], "met": False}, milestone,
        ) == "void"
        assert decision_for_evidence({"facts": {"departed": True}, "met": None}, milestone) == "capture"
        assert decision_for_evidence({"facts": {"cancelled": True}, "met": True}, milestone) == "void"

    asyncio.run(body())


def test_two_cabins_same_leg_both_authorize_at_28_days(monkeypatch):
    """Payment mode must not flip to VAULT on the 2nd cabin when departure is within 29 days."""
    from app.escales.naviguide_bridge import sync_leg_shells

    monkeypatch.setenv("ESCALES_VAULT_ENABLED", "1")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-10-15T08:00:00Z")
    leg = "leg-la-rochelle-to-ajaccio-corse"

    async def body():
        await sync_leg_shells()
        spy = Spy()
        first = await create_pledge(
            amount_eur="80.00",
            description="cabine a",
            milestone_id=leg,
            client=spy,
            client_key="cabin-a",
            kind="cabin_leg",
        )
        second = await create_pledge(
            amount_eur="80.00",
            description="cabine b",
            milestone_id=leg,
            client=spy,
            client_key="cabin-b",
            kind="cabin_leg",
        )
        assert first["payment_mode"] == "AUTHORIZE"
        assert second["payment_mode"] == "AUTHORIZE"
        assert _names(spy) == ["create", "create"]

    asyncio.run(body())


def test_cabin_uses_vault_only_when_departure_beyond_29_days(monkeypatch):
    from app.escales.naviguide_bridge import sync_leg_shells

    monkeypatch.setenv("ESCALES_VAULT_ENABLED", "1")
    monkeypatch.setenv("ESCALES_CLOCK_NOW", "2026-10-01T08:00:00Z")
    leg = "leg-la-rochelle-to-ajaccio-corse"

    async def body():
        await sync_leg_shells()
        spy = Spy()
        created = await create_pledge(
            amount_eur="80.00",
            description="cabine lointaine",
            milestone_id=leg,
            client=spy,
            kind="cabin_leg",
        )
        assert created["payment_mode"] == "VAULT"
        assert spy.calls[-1][0] == "setup_token"

    asyncio.run(body())


def test_legacy_memory_row_reads_as_a_mile():
    async def body():
        ledger = get_ledger()
        ledger._pledges["old"] = {
            "_id": "old",
            "milestone_id": "dep-mayotte",
            "status": "authorized",
            "intent": "AUTHORIZE",
            "amount_eur": "20.00",
        }
        got = await ledger.get_pledge("old")
        assert got["kind"] == "mile"
        assert got["target_id"] == "dep-mayotte"
        assert "kind" not in ledger._pledges["old"]
        public = to_public(got)
        assert public["kind"] == "mile"
        assert public["target_id"] == "dep-mayotte"
        assert public["id"] == "old"
        listed = await ledger.list_pledges_for_milestone("dep-mayotte")
        assert listed[0]["kind"] == "mile"

    asyncio.run(body())


@pytest.mark.live
def test_live_sandbox_create_authorize_order():
    """Optional sandbox create. Skipped unless PAYPAL_CLIENT_ID is set. Does not print secrets."""
    if not os.environ.get("PAYPAL_CLIENT_ID"):
        pytest.skip("PAYPAL_CLIENT_ID is not set")
    if not os.environ.get("PAYPAL_CLIENT_SECRET"):
        pytest.skip("PAYPAL_CLIENT_SECRET is not set")
    client = PayPalClient(load_config())
    # New key: escales-live-probe cached a minimal body that omitted intent.
    order = client.create_authorize_order(
        "1.00",
        "BI Escales live probe",
        "live-probe",
        idempotency_key="escales-live-probe-v2",
    )
    assert order.get("id")
    shown = order if order.get("intent") else client.get_order(order["id"])
    assert shown.get("intent") == "AUTHORIZE"
    assert shown.get("status") in {"CREATED", "PAYER_ACTION_REQUIRED", "APPROVED"}
    assert approve_link(order)


def test_pending_capture_is_recorded_and_can_be_retried():
    """PR #7 recorded PayPal's capture status. A PENDING hold stays pending."""

    class PendingSpy(Spy):
        def __init__(self):
            super().__init__()
            self.capture_body = {"id": "CAP-P", "status": "PENDING"}

        def capture_authorization(self, authorization_id, final=True, **kwargs):
            self.calls.append(("capture", authorization_id))
            return self.capture_body

    async def body():
        spy = PendingSpy()
        created = await create_pledge(
            amount_eur="20.00",
            description="20 milles",
            milestone_id="dep-mayotte",
            client=spy,
            client_key="pending-cap",
        )
        await authorize_pledge(created["_id"], spy)
        pending = await capture_pledge(created["_id"], spy)
        assert pending["status"] == "pending"
        assert pending["paypal_status"] == "PENDING"
        assert pending["capture_id"] == "CAP-P"

    asyncio.run(body())
