"""Per-item funding totals in native currency (no FX conversion)."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from app.channel3_catalog import lookup_catalog_by_project_id
from app.channel3_paypal import (
    major_string_to_minor,
    minor_to_major_display,
    paypal_currency_supported,
)
def _major_to_minor(amount: str, currency: str) -> int:
    return major_string_to_minor(amount, currency)


async def _project_finance_lines(project_id: str) -> list[dict]:
    from app.escales.ledger import _entry_for_project_target, list_finance_entries

    token = str(project_id or "").strip().casefold()
    return [entry for entry in await list_finance_entries() if _entry_for_project_target(entry, token)]


async def fund_snapshot_for_project(project_id: str) -> dict[str, Any]:
    """Captured totals for a catalogue ``project_id`` in the item's native currency."""
    catalog = lookup_catalog_by_project_id(project_id)
    if catalog:
        native = str(catalog.get("price_currency") or "EUR").upper()
        captured = Decimal("0.00")
        refunded = Decimal("0.00")
        donation_count = 0
        for entry in await _project_finance_lines(project_id):
            entry_ccy = str(entry.get("currency") or "EUR").upper()
            if entry_ccy != native:
                continue
            kind = str(entry.get("kind") or "")
            try:
                amount = Decimal(str(entry.get("amount_eur") or "0").replace(",", "."))
            except (InvalidOperation, ValueError):
                amount = Decimal("0.00")
            if kind == "pledge_captured":
                captured += amount
                donation_count += 1
            elif kind == "pledge_refunded":
                refunded += amount
        net = captured - refunded
        text = minor_to_major_display(major_string_to_minor(str(net), native), native)
        refunded_text = minor_to_major_display(major_string_to_minor(str(refunded), native), native)
        return {
            "milestone_id": project_id,
            "currency": native,
            "captured_eur": text,
            "amount_eur": text,
            "donation_count": donation_count,
            "refunded_eur": refunded_text,
        }
    from app.escales.ledger import fund_for_milestone

    try:
        return await fund_for_milestone(project_id)
    except LookupError:
        return {
            "milestone_id": project_id,
            "currency": "EUR",
            "captured_eur": "0.00",
            "amount_eur": "0.00",
            "donation_count": 0,
        }


def enrich_item_funding(
    item: dict[str, Any],
    fund: dict[str, Any],
    *,
    target_amount_minor: Optional[int] = None,
    target_currency: Optional[str] = None,
) -> dict[str, Any]:
    out = dict(item)
    native_ccy = str(
        target_currency
        or item.get("target_currency")
        or fund.get("currency")
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
    target_major = (
        minor_to_major_display(target_minor, native_ccy) if target_minor > 0 else minor_to_major_display(0, native_ccy)
    )

    supported = paypal_currency_supported(native_ccy)
    fund_ccy = str(fund.get("currency") or "EUR").upper()
    funded_minor = 0
    if supported and fund_ccy == native_ccy:
        funded_minor = _major_to_minor(
            str(fund.get("captured_eur") or fund.get("amount_eur") or "0"),
            native_ccy,
        )

    funded_major = minor_to_major_display(funded_minor, native_ccy)
    comparable = supported and fund_ccy == native_ccy and target_minor > 0
    fully_funded = comparable and funded_minor >= target_minor
    if not comparable:
        pct = None
    elif fully_funded:
        pct = 100
    else:
        pct = (funded_minor * 100) // target_minor

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
            "paypal_currency_supported": supported,
        }
    )
    out.pop("eur_funding_supported", None)
    out.pop("indicative_target_eur", None)
    out.pop("fx_source", None)
    out.pop("fx_date", None)
    return out
