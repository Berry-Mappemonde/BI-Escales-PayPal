"""Resolve the marina PayPal payout receiver email for one berth settlement.

The receiver must be the pledge's own marina. A berth pledge names its stopover
(``target_id`` / ``milestone_id``) and its marina (``marina_osm_id`` /
``marina_name``, or the marina name in the description). Only that marina's
catalog row may supply the email. No match falls back to
``ESCALES_MARINA_PAYOUT_EMAIL``; another marina's email is never used.
"""
from __future__ import annotations

import unicodedata
from typing import Any, Optional

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


def _fold(text: str) -> str:
    raw = unicodedata.normalize("NFKD", str(text or ""))
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return " ".join(raw.casefold().replace("’", "'").split())


def _pledge_stop_slug(pledge: dict) -> str:
    from .ledger import _stopover_slug

    for key in ("target_id", "milestone_id"):
        value = str(pledge.get(key) or "").strip()
        if value:
            return _stopover_slug(value)
    return ""


def _stop_marinas(stop_slug: str) -> list[dict]:
    if not stop_slug:
        return []
    from app.bi_marinas_catalog import _normalize_stop_lookup, load_bundled_escale_snapshot

    snapshot = load_bundled_escale_snapshot()
    escales = snapshot.get("escales") if isinstance(snapshot, dict) else {}
    if not isinstance(escales, dict):
        return []
    for name, entry in escales.items():
        key = _normalize_stop_lookup(str(name))
        if not key or not isinstance(entry, dict):
            continue
        if stop_slug != key and not stop_slug.startswith(key + "-"):
            continue
        sections = entry.get("sections") if isinstance(entry.get("sections"), dict) else {}
        mooring = sections.get("mooring") if isinstance(sections.get("mooring"), dict) else {}
        marinas = mooring.get("marinas") if isinstance(mooring, dict) else []
        return [row for row in marinas if isinstance(row, dict)] if isinstance(marinas, list) else []
    return []


def _pledge_marina(pledge: dict, marinas: list[dict]) -> Optional[dict]:
    osm_id = str(pledge.get("marina_osm_id") or pledge.get("marina_id") or "").strip()
    if osm_id:
        for row in marinas:
            if str(row.get("osm_id") or row.get("id") or "").strip() == osm_id:
                return row
    wanted = _fold(str(pledge.get("marina_name") or ""))
    if wanted:
        for row in marinas:
            if _fold(str(row.get("name") or "")) == wanted:
                return row
    description = _fold(str(pledge.get("description") or ""))
    if description:
        # Longest name first so "Port du Sud" never steals "Marina Port du Sud".
        named = sorted(
            (row for row in marinas if _fold(str(row.get("name") or ""))),
            key=lambda row: len(_fold(str(row.get("name") or ""))),
            reverse=True,
        )
        for row in named:
            if _fold(str(row.get("name") or "")) in description:
                return row
    return None


def resolve_marina_payout_email_sync(pledge: dict) -> str:
    """The pledge's own marina email when known, else ``ESCALES_MARINA_PAYOUT_EMAIL``."""
    fallback = marina_payout_email_default()
    try:
        marina = _pledge_marina(pledge, _stop_marinas(_pledge_stop_slug(pledge)))
    except (OSError, ValueError, LookupError):
        marina = None
    if marina:
        found = _email_from_marina_row(marina)
        if found:
            return found
    return fallback
