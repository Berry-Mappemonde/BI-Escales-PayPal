"""Idempotent seed for the Berry-Mappemonde onboard-after-payment demo project."""

from __future__ import annotations

from app.escales.config import demo_project_contact_email
from app.escales.ledger import now_iso
from app.project_onboarding.constants import DEMO_PROJECT_ID, ONBOARDING_LOGO_PATH
from app.project_onboarding.store import get_project, save_project

PROJECT_TEMPLATE = {
    "_id": DEMO_PROJECT_ID,
    "title_fr": "Association Berry-Mappemonde",
    "title_en": "Berry-Mappemonde association",
    "description_fr": (
        "L'association à l'origine de l'expédition voilière Berry-Mappemonde, "
        "qui soutient des projets océan et territoires le long de la route."
    ),
    "description_en": (
        "The association behind the Berry-Mappemonde sailing expedition, "
        "supporting ocean and territory projects along the route."
    ),
    "location_label": "Saint-Maur (Indre), France",
    "lat": 46.807,
    "lng": 1.641,
    "image_url": ONBOARDING_LOGO_PATH,
    "onboarding_status": "pending",
    "contact_email_env": "ESCALES_DEMO_PROJECT_CONTACT_EMAIL",
}


async def seed_demo_onboarding(*, force_contact: str = "") -> dict:
    """Create or refresh the demo onboarding project (does not remove legacy project rows)."""
    existing = await get_project(DEMO_PROJECT_ID)
    contact = (force_contact or demo_project_contact_email() or "project@example.com").strip()
    doc = dict(PROJECT_TEMPLATE)
    doc["seeded_at"] = now_iso()
    doc["contact_email_configured"] = bool(demo_project_contact_email() or force_contact)
    if existing:
        doc["onboarding_status"] = existing.get("onboarding_status") or "pending"
        doc["onboarded_at"] = existing.get("onboarded_at")
        if existing.get("merchant_id"):
            doc["merchant_id"] = existing.get("merchant_id")
    saved = await save_project(doc)
    return {
        "project": saved,
        "contact_email_runtime": contact if force_contact else "<from ESCALES_DEMO_PROJECT_CONTACT_EMAIL>",
    }
