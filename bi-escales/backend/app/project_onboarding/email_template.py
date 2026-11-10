"""Bilingual HTML email for project onboarding (preview + optional send)."""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any, Optional

from app.project_onboarding.constants import ONBOARDING_HELD_STATUS, ONBOARDING_REQUIRED_STATUS

SANDBOX_BANNER = {
    "fr": "Test bac à sable — aucun mouvement réel de fonds.",
    "en": "Sandbox test — no real funds movement.",
}


def _lang(lang: str) -> str:
    return "en" if str(lang or "").lower().startswith("en") else "fr"


def render_onboarding_email(
    *,
    lang: str,
    amount_eur: str,
    foundation_name: str,
    project_title: str,
    action_url: str,
    donation_status: str = "",
    deadline_iso: Optional[str] = None,
) -> dict[str, Any]:
    code = _lang(lang)
    status = str(donation_status or "").strip()
    held = status == ONBOARDING_HELD_STATUS
    onboarding_required = status == ONBOARDING_REQUIRED_STATUS

    deadline_line = ""
    if held and deadline_iso:
        try:
            deadline_dt = datetime.fromisoformat(str(deadline_iso).replace("Z", "+00:00"))
            deadline_text = deadline_dt.strftime("%Y-%m-%d %H:%M UTC")
        except ValueError:
            deadline_text = str(deadline_iso)
        if code == "en":
            deadline_line = f"<p>Funds are held for 30 days (until {html.escape(deadline_text)}).</p>"
        else:
            deadline_line = f"<p>Les fonds sont retenus 30 jours (jusqu'au {html.escape(deadline_text)}).</p>"

    if onboarding_required:
        if code == "en":
            subject = f"Complete PayPal Business setup for {project_title}"
            intro = (
                f"A supporter pledged <strong>{html.escape(amount_eur)} EUR</strong> to "
                f"<strong>{html.escape(project_title)}</strong> "
                f"(foundation: {html.escape(foundation_name)}). "
                f"The project must finish PayPal Business onboarding before the donation can be paid."
            )
            cta = "Set up PayPal Business account"
        else:
            subject = f"Inscription PayPal requise pour {project_title}"
            intro = (
                f"Un donateur a promis <strong>{html.escape(amount_eur)} EUR</strong> pour "
                f"<strong>{html.escape(project_title)}</strong> "
                f"(fondation : {html.escape(foundation_name)}). "
                f"Le projet doit terminer l'inscription PayPal Business avant que le don puisse être payé."
            )
            cta = "Créer un compte PayPal Business"
    elif code == "en":
        subject = f"Funds held for {project_title} — complete PayPal Business setup"
        intro = (
            f"A donation of <strong>{html.escape(amount_eur)} EUR</strong> is held for "
            f"<strong>{html.escape(project_title)}</strong> "
            f"(foundation: {html.escape(foundation_name)})."
        )
        cta = "Set up PayPal Business account"
    else:
        subject = f"Fonds en attente pour {project_title} — finaliser l'inscription PayPal"
        intro = (
            f"Un don de <strong>{html.escape(amount_eur)} EUR</strong> est en attente pour "
            f"<strong>{html.escape(project_title)}</strong> "
            f"(fondation : {html.escape(foundation_name)})."
        )
        cta = "Créer un compte PayPal Business"

    banner = SANDBOX_BANNER[code]
    body = f"""<!DOCTYPE html>
<html lang="{code}">
<head><meta charset="utf-8"/><title>{html.escape(subject)}</title></head>
<body style="font-family: system-ui, sans-serif; line-height: 1.5; max-width: 36em; margin: 1rem auto;">
<p style="background:#fff3cd;padding:0.5rem 1rem;border-radius:4px;"><strong>{html.escape(banner)}</strong></p>
<p>{intro}</p>
{deadline_line}
<p><a href="{html.escape(action_url, quote=True)}" style="display:inline-block;padding:0.6rem 1.2rem;background:#003087;color:#fff;text-decoration:none;border-radius:4px;">{html.escape(cta)}</a></p>
<p style="font-size:0.9em;color:#555;">BI Escales — Pay Only If We Sail</p>
</body>
</html>"""
    return {"subject": subject, "html": body, "lang": code}
