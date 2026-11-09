"""Idempotent fictional seed for onboard-after-payment (C1)."""

from __future__ import annotations

from app.escales.config import demo_project_contact_email
from app.escales.ledger import now_iso
from app.project_onboarding.constants import DEMO_FOUNDATION_ID, DEMO_PROJECT_ID
from app.project_onboarding.store import get_project, save_project

FOUNDATION = {
    "_id": DEMO_FOUNDATION_ID,
    "demo_fake": True,
    "title_fr": "Fondation Fictive des Océans (fictif / sandbox)",
    "title_en": "Fictional Ocean Foundation (fictional / sandbox)",
}

PROJECT_TEMPLATE = {
    "_id": DEMO_PROJECT_ID,
    "demo_fake": True,
    "foundation_id": DEMO_FOUNDATION_ID,
    "title_fr": "Projet Démo — Récif Vivant (fictif / sandbox)",
    "title_en": "Demo Project — Living Reef (fictional / sandbox)",
    "foundation_title_fr": FOUNDATION["title_fr"],
    "foundation_title_en": FOUNDATION["title_en"],
    "onboarding_status": "pending",
    "contact_email_env": "ESCALES_DEMO_PROJECT_CONTACT_EMAIL",
}


async def seed_demo_onboarding(*, force_contact: str = "") -> dict:
    """Create or refresh the fictional foundation + project."""
    existing = await get_project(DEMO_PROJECT_ID)
    contact = (force_contact or demo_project_contact_email() or "project@example.com").strip()
    doc = dict(PROJECT_TEMPLATE)
    doc["seeded_at"] = now_iso()
    doc["contact_email_configured"] = bool(demo_project_contact_email() or force_contact)
    if existing:
        doc["onboarding_status"] = existing.get("onboarding_status") or "pending"
        doc["onboarded_at"] = existing.get("onboarded_at")
    await save_project({**FOUNDATION, "record_kind": "foundation"})
    saved = await save_project(doc)
    return {
        "foundation": FOUNDATION,
        "project": saved,
        "contact_email_runtime": contact if force_contact else "<from ESCALES_DEMO_PROJECT_CONTACT_EMAIL>",
    }
