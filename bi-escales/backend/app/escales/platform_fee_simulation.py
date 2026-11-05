"""Sandbox marina platform fee split recorded in-app when PayPal multiparty IDs are absent."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .config import paypal_berth_platform_fees_on_order, platform_fee_eur
from .ledger import get_ledger, list_finance_entries, now_iso, record_finance


def _money(raw: object) -> Decimal:
    try:
        return Decimal(str(raw or "0").strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def should_simulate_berth_platform_fee(pledge: dict) -> bool:
    if str(pledge.get("kind") or "").strip().lower() != "berth":
        return False
    target = str(pledge.get("target_id") or "")
    return not paypal_berth_platform_fees_on_order(target)


def split_berth_capture_amount(amount_eur: str) -> tuple[str, str]:
    """Return ``(platform_fee_eur, marina_net_eur)`` from a captured berth gross."""
    total = _money(amount_eur)
    fee = min(_money(platform_fee_eur()), total)
    net = total - fee
    return f"{fee:.2f}", f"{net:.2f}"


async def _simulation_finance_exists(pledge_id: str) -> bool:
    for entry in await list_finance_entries():
        if entry.get("kind") == "platform_fee_simulated" and entry.get("pledge_id") == pledge_id:
            return True
    return False


async def apply_simulated_berth_platform_fee(pledge: dict, *, actor: str) -> dict:
    """Attach fee/net on the pledge and append finance lines once per capture."""
    if not should_simulate_berth_platform_fee(pledge):
        return pledge
    pledge_id = str(pledge.get("_id") or "")
    if not pledge_id or await _simulation_finance_exists(pledge_id):
        return pledge

    from .pledges import _identity, finance_milestone_id

    fee, net = split_berth_capture_amount(str(pledge.get("amount_eur") or "0"))
    pledge["platform_fee_eur"] = fee
    pledge["marina_net_eur"] = net
    pledge["platform_fee_simulated"] = True
    at = str(pledge.get("captured_at") or "").strip() or now_iso()
    milestone_id = finance_milestone_id(pledge)
    shared = {
        "pledge_id": pledge_id,
        "milestone_id": milestone_id,
        "currency": pledge.get("currency") or "EUR",
        "actor": actor,
        "at": at,
        "pledge_kind": "berth",
        "target_id": pledge.get("target_id"),
        "simulation": True,
        **_identity(pledge),
    }
    await record_finance(
        "platform_fee_simulated",
        amount_eur=fee,
        status="simulated",
        description="Sandbox platform fee (in-app simulation)",
        **shared,
    )
    await record_finance(
        "marina_net_simulated",
        amount_eur=net,
        status="simulated",
        description="Sandbox net to marina after platform fee",
        **shared,
    )
    return pledge
