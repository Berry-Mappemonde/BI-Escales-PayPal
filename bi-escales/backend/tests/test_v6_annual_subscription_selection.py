"""v6 selection is a constraint on the server's annual catalog, including replay."""
import asyncio
import copy
import pytest
from app.escales import paypal_subscriptions as crew
from app.escales.ledger import reset_ledger

PLAN = {"id": "ANNUAL", "status": "ACTIVE", "billing_cycles": [{"tenure_type": "REGULAR",
    "frequency": {"interval_unit": "YEAR", "interval_count": 1},
    "pricing_scheme": {"fixed_price": {"currency_code": "EUR", "value": "10.0"}}}]}
class Provider:
    def __init__(self): self.calls = []; self.plan = copy.deepcopy(PLAN)
    def get_billing_plan(self, _): return self.plan
    def create_billing_subscription(self, **kwargs):
        self.calls.append(kwargs)
        return {"id": "SUB", "status": "APPROVAL_PENDING"}

@pytest.fixture(autouse=True)
def catalog(monkeypatch):
    monkeypatch.setenv("ESCALES_STORE", "memory")
    reset_ledger()
    async def existing(_): return {"plan_id_en": "ANNUAL", "plan_id_fr": "ANNUAL"}
    monkeypatch.setattr(crew, "ensure_crew_supporter_catalog", existing)
    yield
    reset_ledger()

def create(client, plan="ANNUAL"):
    return crew.create_crew_subscription(client, return_url="https://example.com/return",
        cancel_url="https://example.com/cancel", expected_plan_id=plan, client_key="annual-once")

def test_displayed_plan_mismatch_never_creates():
    client = Provider()
    with pytest.raises(ValueError, match="displayed"): asyncio.run(create(client, "OTHER"))
    assert not client.calls

@pytest.mark.parametrize("change", ["monthly", "price", "tax", "setup", "inactive"])
def test_nonannual_or_extra_price_never_creates(change):
    client = Provider()
    if change == "monthly": client.plan["billing_cycles"][0]["frequency"]["interval_unit"] = "MONTH"
    if change == "price": client.plan["billing_cycles"][0]["pricing_scheme"]["fixed_price"]["value"] = "5.00"
    if change == "tax": client.plan["taxes"] = {"percentage": "20"}
    if change == "setup": client.plan["payment_preferences"] = {"setup_fee": {"value": "1"}}
    if change == "inactive": client.plan["status"] = "INACTIVE"
    with pytest.raises(ValueError, match="10 EUR per year"): asyncio.run(create(client))
    assert not client.calls

def test_concurrent_retry_creates_one_subscription():
    client = Provider()
    async def run():
        rows = await asyncio.gather(*(create(client) for _ in range(3)))
        assert rows[0] == rows[1] == rows[2]
        assert rows[0]["plan_id"] == "ANNUAL"
        assert len(client.calls) == 1
        assert client.calls[0]["idempotency_key"] == "annual-once"
    asyncio.run(run())
