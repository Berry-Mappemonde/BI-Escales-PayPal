"""Travaux météo lancés dans un processus enfant (file asyncio, drapeau allumé).

Chaque fonction est au niveau du module pour être retrouvée par son nom dans
le processus enfant (contexte « spawn »). Le parent tue l'enfant à l'échéance :
un fournisseur lent ne garde ni fil ni connexion ouverte.
"""
from __future__ import annotations

from datetime import datetime, timezone


def refresh_official_grib(around: dict, when_iso: str, force: bool = False) -> dict:
    """Rafraîchit le GRIB officiel au bateau puis l'inscrit au journal."""
    from grib_fetch import maybe_refresh_official  # noqa: PLC0415
    from voyage_store import load_voyage  # noqa: PLC0415
    import voyage_journal as journal  # noqa: PLC0415
    from voyage_clock import OFFICIAL_VOYAGE_ID  # noqa: PLC0415

    when = datetime.fromisoformat(when_iso)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    record = maybe_refresh_official(OFFICIAL_VOYAGE_ID, around, when, force=force)
    try:
        journal.record_grib(record, (load_voyage(OFFICIAL_VOYAGE_ID) or {}).get("clock"), when)
    except Exception:  # noqa: BLE001 - le journal ne fait pas échouer la météo
        pass
    if not record or record.get("status") != "ready":
        raise RuntimeError("grib_unavailable")
    return {"stored": True}
