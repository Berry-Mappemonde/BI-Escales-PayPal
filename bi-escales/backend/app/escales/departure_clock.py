"""Simulated clock settlement for PayPal pledges.

Capture rules (Clément / mini-mix):
- Miles, night, meal, care, berth and project pledges: capture on **departure day**
  when the boat leaves that stopover; void if the stop is cancelled.
- Cabin legs: capture on **departure** from the leg origin; void if cancelled.
- Common fund: captured at once by the treasurer (not driven by this clock).

The simulated clock is ``simulated_now`` (``ESCALES_CLOCK_NOW``, else UTC).
Authorizations are not opened more than 29 days before the relevant departure date.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from .config import AUTH_MAX_DAYS, simulated_now
from .ledger import get_ledger
from .paypal_client import PayPalError
from .pledges import (
    capture_pledge,
    mark_token_delete_pending,
    mark_vault_charge_failed,
    retry_vault_token_delete,
    void_pledge,
)

_STOP_KINDS = frozenset({
    "mile",
    "miles",
    "night",
    "meal",
    "care",
    "berth",
    "project_pledge",
})


def _parse_moment(value: Optional[str]) -> Optional[dt.datetime]:
    text = (value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.astimezone(dt.timezone.utc)


def _days_before(anchor: dt.datetime, now: dt.datetime) -> int:
    return (anchor.date() - now.date()).days


def _cancelled(milestone: dict) -> bool:
    evidence = milestone.get("evidence") or []
    if evidence:
        last = evidence[-1] if isinstance(evidence[-1], dict) else {}
        facts = last.get("facts") if isinstance(last.get("facts"), dict) else {}
        if facts.get("cancelled") is True or facts.get("departed") is False:
            return True
    meta = milestone.get("meta") if isinstance(milestone.get("meta"), dict) else {}
    return meta.get("cancelled") is True


async def departure_milestone(pledge: dict) -> Optional[dict]:
    """Stops and cabin legs whose capture follows ``departure_iso``."""
    from .naviguide_bridge import leg_by_id, leg_milestone_meta, resolve_schedule_milestone

    milestone_id = str(pledge.get("milestone_id") or "")
    kind = str(pledge.get("kind") or "mile").lower()
    if not milestone_id or kind == "common_fund":
        return None
    doc = await resolve_schedule_milestone(milestone_id)
    meta = (doc or {}).get("meta") if isinstance(doc, dict) else None
    if isinstance(meta, dict) and meta.get("capture_on") == "departure":
        return doc
    leg = leg_by_id(milestone_id)
    if leg:
        merged = leg_milestone_meta(leg)
        if isinstance(meta, dict):
            merged = {**merged, **meta}
        if merged.get("capture_on") != "departure":
            return None
        base = dict(doc or {"_id": leg["id"], "evidence": []})
        base["meta"] = merged
        return base
    if kind == "cabin_leg":
        return None
    if kind not in _STOP_KINDS and not milestone_id.startswith(("dep-", "ret-")):
        return None
    if not doc:
        return None
    merged = dict(meta or {})
    merged.setdefault("capture_on", "departure")
    if not merged.get("departure_iso"):
        return None
    base = dict(doc)
    base["meta"] = merged
    return base


async def timing_milestone(pledge: dict) -> Optional[dict]:
    """Milestone that governs the 29-day authorization window."""
    return await departure_milestone(pledge)


async def refuse_cancelled_departure(pledge: dict) -> None:
    """A cancelled stop or leg does not take a new authorization."""
    doc = await timing_milestone(pledge)
    if doc and _cancelled(doc):
        raise ValueError("departure is cancelled")


async def refuse_early_authorization(pledge: dict, *, now: Optional[dt.datetime] = None) -> None:
    """An authorization lasts at most 29 days, so it is not opened earlier."""
    doc = await timing_milestone(pledge)
    if not doc:
        return
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    anchor = _parse_moment(str(meta.get("departure_iso") or ""))
    if anchor is None:
        return
    moment = now or simulated_now()
    if _days_before(anchor, moment) > AUTH_MAX_DAYS:
        raise ValueError("authorization is more than 29 days before departure")


def _vault_failure_detail(exc: Exception) -> str:
    if isinstance(exc, PayPalError):
        blob = f"{exc.body}".upper()
        if "PAYER_ACTION_REQUIRED" in blob:
            return "PAYER_ACTION_REQUIRED"
        return str(exc.body or exc)[:200]
    return str(exc)[:200]


async def _void_cancelled(
    pledge_id: str,
    client: Any,
    *,
    mode: str,
    actions: list[dict],
    effective_at: Optional[dt.datetime] = None,
) -> None:
    try:
        saved = await void_pledge(pledge_id, client, effective_at=effective_at)
        actions.append({"pledge_id": saved["_id"], "action": "void"})
    except Exception as exc:
        if mode == "VAULT":
            detail = _vault_failure_detail(exc)
            await mark_token_delete_pending(pledge_id, detail)
            actions.append({"pledge_id": pledge_id, "action": "token_delete_pending", "detail": detail})
        else:
            actions.append({"pledge_id": pledge_id, "action": "error", "detail": str(exc)})


async def _settle_timed_pledge(
    pledge: dict,
    doc: dict,
    client: Any,
    *,
    moment: dt.datetime,
    actions: list[dict],
) -> None:
    mode = pledge.get("payment_mode") or pledge.get("intent") or "AUTHORIZE"
    status = str(pledge.get("status") or "")
    pledge_id = str(pledge.get("_id") or "")
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    anchor = _parse_moment(str(meta.get("departure_iso") or ""))
    if (
        mode == "VAULT"
        and status == "captured"
        and pledge.get("vault_token_delete_pending")
    ):
        try:
            await retry_vault_token_delete(pledge_id, client)
            actions.append({"pledge_id": pledge_id, "action": "vault_token_deleted"})
        except Exception as exc:
            actions.append({
                "pledge_id": pledge_id,
                "action": "vault_token_delete_pending",
                "detail": _vault_failure_detail(exc),
            })
        return
    if mode == "VAULT" and status == "token_delete_pending":
        if _cancelled(doc):
            await _void_cancelled(
                pledge_id, client, mode=mode, actions=actions, effective_at=moment,
            )
        return
    if mode == "VAULT":
        if status != "vaulted":
            return
    elif status != "authorized":
        return
    try:
        if _cancelled(doc):
            await _void_cancelled(
                pledge_id, client, mode=mode, actions=actions, effective_at=moment,
            )
            return
        if anchor is None or moment.date() < anchor.date():
            actions.append({"pledge_id": pledge_id, "action": "wait"})
            return
        saved = await capture_pledge(pledge_id, client, effective_at=moment)
        actions.append({"pledge_id": saved["_id"], "action": "capture"})
    except Exception as exc:
        if mode == "VAULT":
            detail = _vault_failure_detail(exc)
            await mark_vault_charge_failed(pledge_id, detail)
            actions.append({"pledge_id": pledge_id, "action": "charge_failed", "detail": detail})
        else:
            actions.append({"pledge_id": pledge_id, "action": "error", "detail": str(exc)})


async def run_departure_clock(client: Any, *, now: Optional[dt.datetime] = None) -> dict:
    """Settle authorized or vaulted pledges against the simulated clock."""
    moment = now or simulated_now()
    actions: list[dict] = []
    seen: set[str] = set()
    for pledge in await get_ledger().list_pledges():
        if not pledge:
            continue
        pledge_id = str(pledge.get("_id") or "")
        if not pledge_id or pledge_id in seen:
            continue
        doc = await departure_milestone(pledge)
        if doc is None:
            continue
        seen.add(pledge_id)
        await _settle_timed_pledge(pledge, doc, client, moment=moment, actions=actions)
    return {
        "now": moment.replace(microsecond=0).isoformat(),
        "actions": actions,
    }
