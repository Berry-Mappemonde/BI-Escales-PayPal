"""Seed milestones for local demo / Playwright (near + far horizons)."""
from __future__ import annotations

import datetime as dt


async def ensure_demo_milestones() -> None:
    from app.escales.ledger import get_ledger

    ledger = get_ledger()
    near = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=10)).replace(microsecond=0).isoformat()
    far = "2027-05-15T08:00:00+00:00"
    seeds = (
        ("dep-mayotte", near, "Départ Mayotte"),
        ("dep-fort-de-france", near, "Fort-de-France"),
        ("dep-long-haul", far, "Transatlantic leg (Vault demo)"),
    )
    for milestone_id, arrival_iso, title in seeds:
        await ledger.ensure_milestone(
            milestone_id,
            meta={"title": title, "arrival_iso": arrival_iso},
        )
