"""Capture a departure-day authorization, and void it if the stop is cancelled.

The simulated clock is ``simulated_now`` (``ESCALES_CLOCK_NOW``, else UTC).
A PayPal authorization is not placed more than 29 days before departure.
Before the departure day the hold stays authorized. On that day it is captured.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from .config import AUTH_MAX_DAYS, simulated_now
from .ledger import get_ledger
from .pledges import capture_pledge, void_pledge


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


def _days_before(departure: dt.datetime, now: dt.datetime) -> int:
    return (departure.date() - now.date()).days


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
    """Milestone governed by ``capture_on=departure``, or None."""
    milestone_id = str(pledge.get("milestone_id") or "")
    if not milestone_id:
        return None
    doc = await get_ledger().get_milestone(milestone_id)
    meta = (doc or {}).get("meta") if isinstance(doc, dict) else None
    if isinstance(meta, dict) and meta.get("capture_on") == "departure":
        return doc
    from .naviguide_bridge import leg_by_id, leg_milestone_meta

    leg = leg_by_id(milestone_id)
    if not leg:
        return None
    merged = leg_milestone_meta(leg)
    if isinstance(meta, dict):
        merged = {**merged, **meta}
    if merged.get("capture_on") != "departure":
        return None
    base = dict(doc or {"_id": leg["id"], "evidence": []})
    base["meta"] = merged
    return base


async def refuse_cancelled_departure(pledge: dict) -> None:
    """A cancelled departure does not take a new authorization."""
    doc = await departure_milestone(pledge)
    if doc and _cancelled(doc):
        raise ValueError("departure is cancelled")


async def refuse_early_authorization(pledge: dict, *, now: Optional[dt.datetime] = None) -> None:
    """An authorization lasts at most 29 days, so it is not opened earlier."""
    doc = await departure_milestone(pledge)
    if not doc:
        return
    departure = _parse_moment((doc.get("meta") or {}).get("departure_iso"))
    if departure is None:
        return
    moment = now or simulated_now()
    if _days_before(departure, moment) > AUTH_MAX_DAYS:
        raise ValueError("authorization is more than 29 days before departure")


async def run_departure_clock(client: Any, *, now: Optional[dt.datetime] = None) -> dict:
    """Settle authorized departure pledges against the simulated clock."""
    moment = now or simulated_now()
    actions: list[dict] = []
    for pledge in await get_ledger().list_pledges():
        if not pledge or pledge.get("status") != "authorized":
            continue
        mode = pledge.get("payment_mode") or pledge.get("intent") or "AUTHORIZE"
        if mode == "VAULT":
            continue
        doc = await departure_milestone(pledge)
        if not doc:
            continue
        pledge_id = str(pledge.get("_id") or "")
        try:
            if _cancelled(doc):
                saved = await void_pledge(pledge_id, client)
                actions.append({"pledge_id": saved["_id"], "action": "void"})
                continue
            departure = _parse_moment((doc.get("meta") or {}).get("departure_iso"))
            if departure is None or moment.date() < departure.date():
                actions.append({"pledge_id": pledge_id, "action": "wait"})
                continue
            saved = await capture_pledge(pledge_id, client)
            actions.append({"pledge_id": saved["_id"], "action": "capture"})
        except Exception as exc:
            actions.append({"pledge_id": pledge_id, "action": "error", "detail": str(exc)})
    return {
        "now": moment.replace(microsecond=0).isoformat(),
        "actions": actions,
    }
