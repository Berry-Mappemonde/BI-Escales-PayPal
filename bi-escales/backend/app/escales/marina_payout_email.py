"""Resolve marina PayPal payout receiver email for berth settlements."""
from __future__ import annotations

import os
from typing import Any

from .config import marina_payout_email_default


def _valid_email(raw: str) -> str:
    text = (raw or "").strip()
    return text if "@" in text else ""


def _email_from_marina_row(row: dict[str, Any]) -> str:
    for key in ("payout_email", "paypal_payout_email", "capitainerie_email", "email"):
        found = _valid_email(str(row.get(key) or ""))
        if found:
            return found
    return ""


def resolve_marina_payout_email_sync(pledge: dict) -> str:
    """Marina record email when present, else ``ESCALES_MARINA_PAYOUT_EMAIL``."""
    fallback = marina_payout_email_default()
    try:
        from app.bi_marinas_catalog import load_bundled_escale_snapshot

        snapshot = load_bundled_escale_snapshot()
        escales = snapshot.get("escales") if isinstance(snapshot, dict) else {}
        if isinstance(escales, dict):
            for entry in escales.values():
                if not isinstance(entry, dict):
                    continue
                mooring = (entry.get("sections") or {}).get("mooring") if isinstance(entry.get("sections"), dict) else {}
                marinas = mooring.get("marinas") if isinstance(mooring, dict) else []
                if not isinstance(marinas, list):
                    continue
                for marina in marinas:
                    if not isinstance(marina, dict):
                        continue
                    found = _email_from_marina_row(marina)
                    if found:
                        return found
    except OSError:
        pass
    return fallback
