"""Seed milestones inside the 29-day authorization window for unit tests."""
from __future__ import annotations

import datetime as dt

NEAR_IDS = ("dep-mayotte", "dep-fort-de-france", "other", "mayotte")


def near_iso() -> str:
    moment = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=10)
    return moment.replace(microsecond=0).isoformat()


async def seed_near(*ids: str) -> None:
    from app.escales.ledger import get_ledger

    arrival = near_iso()
    ledger = get_ledger()
    for milestone_id in ids or NEAR_IDS:
        await ledger.ensure_milestone(
            milestone_id,
            meta={"title": milestone_id, "arrival_iso": arrival},
        )
