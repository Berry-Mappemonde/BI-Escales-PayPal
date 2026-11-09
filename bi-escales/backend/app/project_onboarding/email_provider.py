"""Optional Cloudflare Email Service delivery (off by default)."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from app.escales.config import email_enabled

log = logging.getLogger("escales.project_onboarding.email")


def allowlist_allows(recipient: str) -> bool:
    """Recipient domain must match ESCALES_EMAIL_ALLOWLIST when configured."""
    allow = (os.environ.get("ESCALES_EMAIL_ALLOWLIST") or "").strip()
    if not allow:
        return True
    domains = {part.strip().lower().lstrip("@") for part in allow.split(",") if part.strip()}
    email = str(recipient or "").strip().lower()
    if "@" not in email:
        return False
    domain = email.split("@", 1)[1]
    return domain in domains


async def send_html_email(*, to: str, subject: str, html: str) -> dict[str, Any]:
    if not email_enabled():
        return {"sent": False, "reason": "disabled"}
    if not allowlist_allows(to):
        return {"sent": False, "reason": "allowlist"}
    api_url = (os.environ.get("ESCALES_EMAIL_API_URL") or "").strip()
    api_token = (os.environ.get("ESCALES_EMAIL_API_TOKEN") or "").strip()
    if not api_url or not api_token:
        return {"sent": False, "reason": "not_configured"}
    payload = {
        "to": to,
        "subject": subject,
        "html": html,
    }
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(api_url, json=payload, headers=headers)
    if response.status_code >= 400:
        log.warning("email provider HTTP %s", response.status_code)
        return {"sent": False, "reason": "provider_error", "status": response.status_code}
    return {"sent": True}
