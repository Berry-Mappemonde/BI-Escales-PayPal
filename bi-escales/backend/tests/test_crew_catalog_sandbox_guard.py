"""Catalog provisioning never touches live; existing v2 catalogs are reused."""
import asyncio
import pytest
from app.escales import paypal_subscriptions as crew


@pytest.mark.parametrize("environment", ["live", "", "production"])
def test_catalog_guard_precedes_provider_calls(monkeypatch, environment):
    monkeypatch.setenv("PAYPAL_ENV", environment)
    with pytest.raises(ValueError, match="sandbox"):
        asyncio.run(crew.ensure_crew_supporter_catalog(object()))


def test_concurrent_ensure_reuses_ready_v2_without_provider(monkeypatch):
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")
    async def row():
        return {"product_id_en": "PROD-EN", "product_id_fr": "PROD-FR",
                "plan_id_en": "ANNUAL-EN", "plan_id_fr": "ANNUAL-FR"}
    monkeypatch.setattr(crew, "_catalog_row", row)
    async def run():
        rows = await asyncio.gather(*(crew.ensure_crew_supporter_catalog(object()) for _ in range(4)))
        assert all(r["plan_id_en"] == "ANNUAL-EN" and r["plan_id_fr"] == "ANNUAL-FR" and r["idempotent"] for r in rows)
    asyncio.run(run())
