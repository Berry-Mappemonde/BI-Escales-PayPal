"""F03/F04: server catalog authority and concurrent replay, no provider network."""
import asyncio
import copy
import pytest
from app.escales import paypal_subscriptions as subscriptions
from app.escales.ledger import reset_ledger

PLAN = {"id": "PLAN", "status": "ACTIVE", "billing_cycles": [{"tenure_type": "REGULAR", "frequency": {"interval_unit": "MONTH", "interval_count": 1}, "pricing_scheme": {"fixed_price": {"currency_code": "EUR", "value": "5.00"}}}]}
class Provider:
    def __init__(self):
        self.calls = []
        self.plan = copy.deepcopy(PLAN)
    def get_billing_plan(self, plan_id):
        assert plan_id == "PLAN"
        return self.plan
    def create_billing_subscription(self, **kwargs):
        self.calls.append(kwargs)
        return {"id": "SUB", "status": "APPROVAL_PENDING"}

@pytest.fixture(autouse=True)
def memory(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    reset_ledger()
    async def catalog(_client):
        return {"plan_id_fr": "PLAN", "plan_id_en": "PLAN"}
    monkeypatch.setattr(subscriptions, "ensure_crew_supporter_catalog", catalog)
    yield
    reset_ledger()

def create(client, plan="PLAN"):
    return subscriptions.create_crew_subscription(client, return_url="https://test.invalid/return", cancel_url="https://test.invalid/cancel", client_key="stable-audit-attempt", expected_plan_id=plan)

def test_F03_displayed_plan_mismatch_prevents_provider_creation():
    client = Provider()
    with pytest.raises(ValueError, match="displayed"):
        asyncio.run(create(client, "UNPERMITTED"))
    assert client.calls == []

@pytest.mark.parametrize("field,value", [("value", "6.00"), ("currency_code", "USD")])
def test_F03_price_is_server_verified(field, value):
    client = Provider()
    client.plan["billing_cycles"][0]["pricing_scheme"]["fixed_price"][field] = value
    with pytest.raises(ValueError, match="pricing"):
        asyncio.run(create(client))
    assert client.calls == []

def test_F04_concurrent_same_attempt_creates_one_provider_resource_and_cache_row():
    client = Provider()
    async def run():
        results = await asyncio.gather(create(client), create(client), create(client))
        assert results[0] == results[1] == results[2]
        assert results[0]["plan_id"] == "PLAN"
        assert len(client.calls) == 1
        assert client.calls[0]["idempotency_key"] == "stable-audit-attempt"
        rows = await subscriptions.list_finance_entries()
        assert len([row for row in rows if row.get("kind") == subscriptions.SUBSCRIPTION_CREATE_CACHE_KIND]) == 1
    asyncio.run(run())


@pytest.mark.parametrize("extra", [{"payment_preferences": {"setup_fee": {"value": "10.00", "currency_code": "EUR"}}}, {"taxes": {"percentage": "20"}}])
def test_F03_unadvertised_extra_price_is_refused(extra):
    client = Provider()
    client.plan.update(extra)
    with pytest.raises(ValueError, match="pricing"):
        asyncio.run(create(client))
    assert client.calls == []
