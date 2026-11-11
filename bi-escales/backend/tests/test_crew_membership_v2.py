"""Crew membership is the association membership (adhésion): 10 EUR per year.

The first catalog (5 EUR per month) is kept on record and never touched: its plans
still verify for existing subscribers, and the app shows and sells only the new plans.
"""
from __future__ import annotations

import asyncio
import copy
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.escales.captain import chat
from app.escales.ledger import list_finance_entries, record_finance, reset_ledger
from app.escales.paypal_subscriptions import (
    CREW_LABELS,
    CREW_LEGACY_LABELS,
    CREW_LEGACY_SETUP_KEY,
    CREW_PLAN_AMOUNT_EUR,
    CREW_PLAN_ID_EN_FALLBACK,
    CREW_PLAN_INTERVAL_UNIT,
    CREW_SETUP_KEY,
    approve_crew_subscription,
    create_crew_subscription,
    crew_supporter_plan_ids,
    ensure_crew_supporter_catalog,
    legacy_crew_plan_ids,
    public_crew_supporter_plan_id,
    resolve_crew_supporter_plan_id,
)
from app.routers.escales import router, set_paypal_client_factory

ADMIN = {"x-admin-key": "test-admin-key"}
LEGACY_EN, LEGACY_FR = "P-LEGACY-EN-5-MONTH", "P-LEGACY-FR-5-MONTH"


class PayPalSpy:
    """A PayPal stand-in with no way to update or delete a product or a plan."""

    def __init__(self):
        self.products: list[dict] = []
        self.plans: list[dict] = []
        self.created_products: list[dict] = []
        self.created_plans: list[dict] = []
        self.subscriptions: list[dict] = []
        self.remote_plan = ""
        self.remote_status = "ACTIVE"

    def iter_billing_product_pages(self):
        yield {"products": self.products}

    def list_billing_plans(self, *, product_id: str, page_size: int = 20):
        return {"plans": [plan for plan in self.plans if plan["product_id"] == product_id]}

    def create_billing_product(self, *, name, description, idempotency_key):
        row = {"id": f"PROD-{len(self.products) + 1}", "name": name, "description": description, "key": idempotency_key}
        self.products.append(row)
        self.created_products.append(row)
        return {"id": row["id"]}

    def create_billing_plan(self, *, product_id, name, amount_eur, interval_unit, idempotency_key):
        row = {
            "id": f"PLAN-{len(self.plans) + 1}", "name": name, "product_id": product_id,
            "amount_eur": amount_eur, "interval_unit": interval_unit, "key": idempotency_key,
        }
        self.plans.append(row)
        self.created_plans.append(row)
        return {"id": row["id"]}

    def create_billing_subscription(self, **kwargs):
        self.subscriptions.append(kwargs)
        return {"id": f"I-NEW-{len(self.subscriptions)}", "status": "APPROVAL_PENDING", "links": [{"rel": "approve", "href": "https://paypal.test/approve"}]}

    def get_subscription(self, subscription_id: str):
        return {"id": subscription_id, "plan_id": self.remote_plan, "status": self.remote_status, "subscriber": {"email_address": "member@example.com"}}


@pytest.fixture(autouse=True)
def memory(monkeypatch):
    monkeypatch.setenv("ESCALES_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    monkeypatch.setenv("ESCALES_ADMIN_KEY", "test-admin-key")
    reset_ledger()
    yield
    reset_ledger()
    set_paypal_client_factory(None)


def run(coro):
    return asyncio.run(coro)


async def _seed_legacy_catalog() -> dict:
    return await record_finance(
        "subscription_catalog_ready",
        setup_key=CREW_LEGACY_SETUP_KEY,
        product_id_en="PROD-LEGACY-EN", plan_id_en=LEGACY_EN,
        product_id_fr="PROD-LEGACY-FR", plan_id_fr=LEGACY_FR,
    )


async def _legacy_rows() -> list[dict]:
    return [row for row in await list_finance_entries() if row.get("setup_key") == CREW_LEGACY_SETUP_KEY]


def test_the_plan_is_ten_euros_per_year():
    assert CREW_PLAN_AMOUNT_EUR == "10.00"
    assert CREW_PLAN_INTERVAL_UNIT == "YEAR"
    assert CREW_SETUP_KEY != CREW_LEGACY_SETUP_KEY
    assert CREW_LEGACY_SETUP_KEY == "crew_supporter_catalog"


def test_setup_creates_two_products_and_two_yearly_plans_at_ten_euros():
    spy = PayPalSpy()
    out = run(ensure_crew_supporter_catalog(spy))
    assert out["idempotent"] is False
    assert [plan["name"] for plan in spy.created_plans] == [CREW_LABELS["en"]["plan_name"], CREW_LABELS["fr"]["plan_name"]]
    assert {plan["amount_eur"] for plan in spy.created_plans} == {"10.00"}
    assert {plan["interval_unit"] for plan in spy.created_plans} == {"YEAR"}
    assert [product["name"] for product in spy.created_products] == ["Crew membership", "Adhésion Crew"]
    for product in spy.created_products:
        assert "10 EUR" in product["description"]
        assert "month" not in product["description"].lower() and "mensuel" not in product["description"].lower()
    assert out["plan_id_en"] == spy.created_plans[0]["id"]
    assert out["plan_id_fr"] == spy.created_plans[1]["id"]


def test_setup_uses_request_ids_of_its_own_so_paypal_cannot_replay_the_first_catalog():
    spy = PayPalSpy()
    run(ensure_crew_supporter_catalog(spy))
    keys = [row["key"] for row in (*spy.created_products, *spy.created_plans)]
    assert keys == [
        f"product-en-{CREW_SETUP_KEY}", f"product-fr-{CREW_SETUP_KEY}",
        f"plan-en-{CREW_SETUP_KEY}", f"plan-fr-{CREW_SETUP_KEY}",
    ]
    assert all(CREW_LEGACY_SETUP_KEY not in key for key in keys)


def test_setup_is_idempotent_and_calls_paypal_once():
    spy = PayPalSpy()
    first = run(ensure_crew_supporter_catalog(spy))
    second = run(ensure_crew_supporter_catalog(spy))
    assert second["idempotent"] is True
    assert (second["plan_id_en"], second["plan_id_fr"]) == (first["plan_id_en"], first["plan_id_fr"])
    assert len(spy.created_products) == 2 and len(spy.created_plans) == 2


def test_setup_leaves_the_first_catalog_exactly_as_it_was():
    async def body():
        await _seed_legacy_catalog()
        before = copy.deepcopy(await _legacy_rows())
        spy = PayPalSpy()
        # The 5 EUR per month product and plans exist on PayPal under their old names.
        spy.products = [{"id": "PROD-LEGACY-EN", "name": CREW_LEGACY_LABELS["en"]["product_name"]}, {"id": "PROD-LEGACY-FR", "name": CREW_LEGACY_LABELS["fr"]["product_name"]}]
        spy.plans = [
            {"id": LEGACY_EN, "name": CREW_LEGACY_LABELS["en"]["plan_name"], "product_id": "PROD-LEGACY-EN"},
            {"id": LEGACY_FR, "name": CREW_LEGACY_LABELS["fr"]["plan_name"], "product_id": "PROD-LEGACY-FR"},
        ]
        out = await ensure_crew_supporter_catalog(spy)
        assert await _legacy_rows() == before
        # New products and plans were created beside them; the old ones were not reused.
        assert len(spy.created_products) == 2 and len(spy.created_plans) == 2
        assert out["plan_id_en"] not in (LEGACY_EN, LEGACY_FR)
        assert out["plan_id_fr"] not in (LEGACY_EN, LEGACY_FR)
        assert {plan["id"] for plan in spy.plans} >= {LEGACY_EN, LEGACY_FR}
        # The spy has no update, patch, deactivate or delete: any such call would have raised.
        assert not [name for name in dir(spy) if name.startswith(("update", "patch", "delete", "deactivate"))]

    run(body())


def test_a_catalog_already_on_paypal_is_found_by_its_new_names_not_created_twice():
    spy = PayPalSpy()
    spy.products = [{"id": "PROD-A", "name": "Crew membership"}, {"id": "PROD-B", "name": "Adhésion Crew"}]
    spy.plans = [
        {"id": "PLAN-A", "name": CREW_LABELS["en"]["plan_name"], "product_id": "PROD-A"},
        {"id": "PLAN-B", "name": CREW_LABELS["fr"]["plan_name"], "product_id": "PROD-B"},
    ]
    out = run(ensure_crew_supporter_catalog(spy))
    assert (out["plan_id_en"], out["plan_id_fr"]) == ("PLAN-A", "PLAN-B")
    assert spy.created_products == [] and spy.created_plans == []


def test_with_only_the_first_catalog_the_app_offers_no_plan():
    async def body():
        await _seed_legacy_catalog()
        spy = PayPalSpy()
        assert await public_crew_supporter_plan_id("en") is None
        assert await public_crew_supporter_plan_id("fr") is None
        # The lookup neither creates anything nor falls back to a 5 EUR per month plan.
        assert await resolve_crew_supporter_plan_id(spy, lang="en") is None
        assert await resolve_crew_supporter_plan_id(spy, lang="fr") is None
        assert spy.created_products == [] and spy.created_plans == []

    run(body())


def test_after_setup_the_app_resolves_the_new_plan_ids():
    async def body():
        await _seed_legacy_catalog()
        spy = PayPalSpy()
        out = await ensure_crew_supporter_catalog(spy)
        assert await public_crew_supporter_plan_id("en") == out["plan_id_en"]
        assert await public_crew_supporter_plan_id("fr") == out["plan_id_fr"]
        assert await resolve_crew_supporter_plan_id(spy, lang="fr") == out["plan_id_fr"]

    run(body())


def test_a_new_subscription_is_made_on_the_yearly_plan():
    async def body():
        await _seed_legacy_catalog()
        spy = PayPalSpy()
        made = await create_crew_subscription(spy, return_url="https://a.test/r", cancel_url="https://a.test/c", client_key="buyer-1", lang="en")
        yearly_en = next(plan for plan in spy.created_plans if plan["name"] == CREW_LABELS["en"]["plan_name"])
        assert made["plan_id"] == yearly_en["id"]
        assert spy.subscriptions[0]["plan_id"] == yearly_en["id"]
        assert yearly_en["amount_eur"] == "10.00" and yearly_en["interval_unit"] == "YEAR"

    run(body())


def test_plan_ids_that_count_as_crew_are_the_new_ones_and_the_first_catalog_ones():
    async def body():
        await _seed_legacy_catalog()
        spy = PayPalSpy()
        out = await ensure_crew_supporter_catalog(spy)
        assert await legacy_crew_plan_ids() == {LEGACY_EN, LEGACY_FR, CREW_PLAN_ID_EN_FALLBACK}
        assert await crew_supporter_plan_ids(spy) == {out["plan_id_en"], out["plan_id_fr"], LEGACY_EN, LEGACY_FR, CREW_PLAN_ID_EN_FALLBACK}

    run(body())


@pytest.mark.parametrize("legacy_plan", [LEGACY_EN, LEGACY_FR, CREW_PLAN_ID_EN_FALLBACK])
def test_an_existing_subscriber_on_a_five_euro_monthly_plan_still_verifies(legacy_plan):
    async def body():
        await _seed_legacy_catalog()
        spy = PayPalSpy()
        spy.remote_plan = legacy_plan
        row = await approve_crew_subscription(spy, subscription_id="I-OLD-1", plan_id=legacy_plan)
        assert row["status"] == "ACTIVE"
        assert row["plan_id"] == legacy_plan

    run(body())


def test_a_new_subscriber_on_the_yearly_plan_verifies():
    async def body():
        spy = PayPalSpy()
        out = await ensure_crew_supporter_catalog(spy)
        spy.remote_plan = out["plan_id_fr"]
        row = await approve_crew_subscription(spy, subscription_id="I-NEW-1", plan_id=out["plan_id_fr"])
        assert row["status"] == "ACTIVE" and row["plan_id"] == out["plan_id_fr"]

    run(body())


def test_a_subscription_on_any_other_plan_is_still_refused():
    async def body():
        await _seed_legacy_catalog()
        spy = PayPalSpy()
        spy.remote_plan = "P-SOMEONE-ELSES-PLAN"
        with pytest.raises(ValueError, match="does not match the Crew membership plan"):
            await approve_crew_subscription(spy, subscription_id="I-FOREIGN", plan_id="P-SOMEONE-ELSES-PLAN")

    run(body())


def test_a_legacy_plan_that_is_not_active_is_still_refused():
    async def body():
        await _seed_legacy_catalog()
        spy = PayPalSpy()
        spy.remote_plan, spy.remote_status = LEGACY_EN, "APPROVAL_PENDING"
        with pytest.raises(ValueError, match="APPROVAL_PENDING"):
            await approve_crew_subscription(spy, subscription_id="I-OLD-2", plan_id=LEGACY_EN)

    run(body())


@pytest.fixture
def api():
    spy = PayPalSpy()
    set_paypal_client_factory(lambda *_args, **_kwargs: spy)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client, spy
    set_paypal_client_factory(None)


def test_the_admin_setup_route_is_what_creates_the_yearly_plans(api):
    client, spy = api
    run(_seed_legacy_catalog())
    # Before: the public plan route offers nothing, and reading it creates nothing.
    assert client.get("/api/escales/paypal/subscriptions/plan?lang=en").json()["plan_id"] is None
    assert client.get("/api/escales/features").json()["crew_supporter_plan_id"] is None
    assert spy.created_plans == []
    # The route needs the treasurer key.
    assert client.post("/api/escales/paypal/subscriptions/setup").status_code == 401
    assert spy.created_plans == []

    setup = client.post("/api/escales/paypal/subscriptions/setup", headers=ADMIN)
    assert setup.status_code == 200, setup.text
    body = setup.json()
    assert body["idempotent"] is False
    assert {plan["amount_eur"] for plan in spy.created_plans} == {"10.00"}
    assert {plan["interval_unit"] for plan in spy.created_plans} == {"YEAR"}

    # After: the app resolves the new ids in both languages.
    assert client.get("/api/escales/paypal/subscriptions/plan?lang=en").json()["plan_id"] == body["plan_id_en"]
    assert client.get("/api/escales/paypal/subscriptions/plan?lang=fr").json()["plan_id"] == body["plan_id_fr"]
    assert client.get("/api/escales/features").json()["crew_supporter_plan_id"] in (body["plan_id_en"], body["plan_id_fr"])
    # Running it again changes nothing.
    again = client.post("/api/escales/paypal/subscriptions/setup", headers=ADMIN).json()
    assert again["idempotent"] is True and len(spy.created_plans) == 2


@pytest.mark.parametrize(
    "question, lang, expected",
    [
        ("How much is the Crew membership?", "en", "10 € per year"),
        ("How do I join the association?", "en", "10 € per year"),
        ("I want to become a member", "en", "association's membership (adhésion)"),
        ("Combien coûte l'adhésion ?", "fr", "10 € par an"),
        ("Comment adhérer à l'association ?", "fr", "10 € par an"),
        ("C'est quoi l'abonnement Crew ?", "fr", "adhésion à l'association"),
    ],
)
def test_the_captain_answers_membership_questions_from_a_fixed_rule(question, lang, expected):
    reply = run(chat(question, lang=lang))
    assert expected in reply["reply"]
    assert reply["rule_by_design"] is True
    assert reply["model_source"] == {"provider": "rules", "model": ""}
    assert reply["suggested_pledge"] is None and reply["cart"] is None
    # No price of the first catalog, no monthly wording, no link.
    lowered = reply["reply"].lower()
    for stale in ("5 €", "5 eur", "per month", "monthly", "par mois", "mensuel", "http"):
        assert stale not in lowered


def test_a_pledge_request_is_still_a_pledge_not_a_membership_answer():
    reply = run(chat("Sponsor 20 miles near Mayotte", lang="en"))
    assert "10 € per year" not in reply["reply"]
    assert reply["suggested_pledge"]["amount_eur"] == "20.00"
