"""Explicit capture-review setup for tests focused on payment behavior."""
from app.escales.config import simulated_now
from app.escales.milestones import record_captain_review_approval
from app.escales.naviguide_bridge import resolve_milestone
from app.escales.pledges import get_ledger


async def propose_capture_review(milestone_id):
    mid = resolve_milestone(milestone_id) or milestone_id
    await get_ledger().set_proposal(mid, {
        "proposal": "capture", "at": simulated_now().isoformat(),
    })
    return mid


async def approve_capture_review(milestone_id):
    return await record_captain_review_approval(await propose_capture_review(milestone_id))
