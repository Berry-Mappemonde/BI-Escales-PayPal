"""Sandbox judge-moment actions for a single demo stop (La Rochelle)."""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from .config import simulated_now
from .departure_clock import _parse_moment, run_departure_clock_for_milestone
from .milestones import demo_arrival_approval
from .naviguide_bridge import resolve_milestone, resolve_schedule_milestone
from .pledges import get_ledger, void_pledge

DEMO_STOP_MILESTONE_ID = "dep-la-rochelle"


def _normalize_action(saved: dict, action: str) -> dict:
    row: dict[str, Any] = {
        "pledge_id": saved.get("_id") or saved.get("id"),
        "action": action,
        "status": saved.get("status"),
    }
    if saved.get("capture_id"):
        row["capture_id"] = saved["capture_id"]
    if saved.get("void_id"):
        row["void_id"] = saved["void_id"]
    return row


async def _arrival_moment(milestone_id: str) -> dt.datetime:
    doc = await resolve_schedule_milestone(milestone_id, read_only=True)
    meta = (doc or {}).get("meta") or {}
    anchor = _parse_moment(str(meta.get("arrival_iso") or ""))
    if anchor is None:
        raise ValueError("arrival date is missing for this stop")
    return anchor


async def demo_simulate_arrival(milestone_id: str, client: Any) -> dict:
    """Run the departure clock for the demo stop at its arrival time.

    The treasurer pressing this button is the approval, for this call only: no
    Captain proposal is overwritten and no ``captain_review_approved`` finance
    row is written, so the real voyage clock (12 Nov) never sees an approval
    nobody gave (HamidZ11 review on #149, blocker 2).
    """
    mid = resolve_milestone(milestone_id) or milestone_id
    arrival = await _arrival_moment(mid)
    arrival_iso = arrival.replace(microsecond=0).isoformat()
    with demo_arrival_approval(mid):
        settled = await run_departure_clock_for_milestone(client, mid, now=arrival)
    actions = []
    for entry in settled.get("actions") or []:
        pledge_id = entry.get("pledge_id")
        if not pledge_id:
            continue
        saved = await get_ledger().get_pledge(str(pledge_id))
        if not saved:
            actions.append(entry)
            continue
        row = dict(entry)
        if saved.get("capture_id"):
            row["capture_id"] = saved["capture_id"]
        if saved.get("void_id"):
            row["void_id"] = saved["void_id"]
        actions.append(row)
    return {
        "milestone_id": mid,
        "now": settled.get("now") or arrival_iso,
        "captain_review_approved_at": arrival_iso,
        "approval_persisted": False,
        "actions": actions,
    }


async def _void_milestone_pledges(
    milestone_id: str,
    client: Any,
    *,
    moment: Optional[dt.datetime] = None,
) -> list[dict]:
    effective = moment or simulated_now()
    actions: list[dict] = []
    pledges = await get_ledger().list_pledges_for_milestone(milestone_id)
    for pledge in pledges:
        status = str(pledge.get("status") or "")
        if status != "authorized":
            continue
        pledge_id = str(pledge.get("_id") or "")
        if not pledge_id:
            continue
        try:
            saved = await void_pledge(pledge_id, client, effective_at=effective)
            actions.append(_normalize_action(saved, "void"))
        except Exception as exc:
            actions.append({
                "pledge_id": pledge_id,
                "action": "error",
                "detail": str(exc),
            })
    return actions


async def demo_cancel_stop(milestone_id: str, client: Any) -> dict:
    mid = resolve_milestone(milestone_id) or milestone_id
    await get_ledger().set_demo_cancelled(mid, True)
    moment = simulated_now()
    actions = await _void_milestone_pledges(mid, client, moment=moment)
    return {"milestone_id": mid, "demo_cancelled": True, "actions": actions}


async def demo_reset_stop(milestone_id: str) -> dict:
    mid = resolve_milestone(milestone_id) or milestone_id
    await get_ledger().set_demo_cancelled(mid, False)
    return {"milestone_id": mid, "demo_cancelled": False, "actions": []}
