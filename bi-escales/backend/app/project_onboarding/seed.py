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
        "Association loi 1901 basée à Saint-Maur (Indre), Berry-Mappemonde organise une expédition "
        "à la voile de 36 mois, en voiliers de série, qui relie le Berry, terre sans littoral au centre "
        "de la France, aux 13 territoires français d'Outre-mer. L'association crée des liens durables "
        "entre ces territoires (jumelages, échanges, partenariats), mène des actions pédagogiques dans "
        "les écoles, sensibilise aux enjeux maritimes, agricoles et environnementaux, et documente "
        "l'aventure par un livre, une série documentaire et une exposition itinérante."
    ),
    "description_en": (
        "A French non-profit based in Saint-Maur (Indre), Berry-Mappemonde is organising a 36-month "
        "sailing expedition on production sailboats, linking the Berry, a landlocked region in the heart "
        "of France, to France's 13 overseas territories. The association builds lasting ties between "
        "these places (twinnings, exchanges, partnerships), runs school programmes, raises awareness of "
        "maritime, farming and environmental issues, and documents the journey through a book, a "
        "documentary series and a travelling exhibition."
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
