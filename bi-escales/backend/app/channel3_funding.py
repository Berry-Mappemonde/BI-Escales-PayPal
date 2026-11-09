"""Per-item funding totals in native currency (pledges stored in EUR)."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from app.channel3_money import minor_to_major_str
from app.gear_projects_catalog import funded_percent


def _eur_to_minor(amount_eur: str) -> int:
    try:
        value = Decimal(str(amount_eur or "0").replace(",", "."))
    except (InvalidOperation, ValueError):
        return 0
    return int((value * Decimal("100")).quantize(Decimal("1")))


async def fund_snapshot_for_project(project_id: str) -> dict[str, Any]:
    from app.escales.ledger import fund_for_milestone

    try:
        return await fund_for_milestone(project_id)
    except LookupError:
        return {
            "milestone_id": project_id,
            "currency": "EUR",
            "captured_eur": "0.00",
            "amount_eur": "0.00",
        }


def enrich_item_funding(
    item: dict[str, Any],
    fund: dict[str, Any],
    *,
    target_amount_minor: Optional[int] = None,
    target_currency: Optional[str] = None,
) -> dict[str, Any]:
    """Attach funded_* fields; EUR pledges only count toward EUR targets."""
    out = dict(item)
    native_ccy = str(
        target_currency
        or item.get("target_currency")
        or item.get("catalog_default_target_currency")
        or item.get("price_currency")
        or "EUR"
    ).upper()
    target_minor = int(
        target_amount_minor
        if target_amount_minor is not None
        else item.get("catalog_default_target_amount_minor")
        or item.get("price_amount_minor")
        or 0
    )
    target_major = minor_to_major_str(target_minor) if target_minor > 0 else "0.00"

    eur_funding_supported = native_ccy == "EUR"
    funded_minor = 0
    if eur_funding_supported:
        funded_minor = _eur_to_minor(str(fund.get("captured_eur") or fund.get("amount_eur") or "0"))

    funded_major = minor_to_major_str(funded_minor)
    pct = (
        funded_percent(funded_major, target_major, amount_currency=native_ccy, goal_currency=native_ccy)
        if target_minor > 0 and eur_funding_supported
        else None
    )
    fully_funded = pct is not None and pct >= 100

    out.update(
        {
            "target_amount_minor": target_minor,
            "target_currency": native_ccy,
            "target_display": target_major,
            "funded_amount_minor": funded_minor,
            "funded_currency": native_ccy,
            "funded_display": funded_major,
            "funded_pct": pct,
            "fully_funded": fully_funded,
            "eur_funding_supported": eur_funding_supported,
            "indicative_target_eur": None,
            "fx_source": None,
            "fx_date": None,
        }
    )
    return out
