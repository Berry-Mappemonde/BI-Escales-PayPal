"""Copie ajout-seule des perles anciennes vers la clé canonique.

Ne supprime aucune perle. Refuse de démarrer si le service
naviguide-simulator est actif. Sauvegarde le sqlite avant toute écriture.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("naviguide-simulator.migrate_pearl_keys")

SERVICE_UNIT = "naviguide-simulator"

_KEY_COORDS = re.compile(
    r"^(-?\d+(?:\.\d+)?):(-?\d+(?:\.\d+)?):(\d+)",
)


def _coords_from_key(key: str) -> tuple[float, float, int] | None:
    match = _KEY_COORDS.match(str(key or ""))
    if not match:
        return None
    try:
        return float(match.group(1)), float(match.group(2)), int(match.group(3))
    except ValueError:
        return None


def _service_check_skipped() -> bool:
    flag = os.environ.get("NAVIGUIDE_TEST_SKIP_SERVICE_CHECK", "").strip().lower()
    if flag not in {"1", "true", "yes"}:
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    log.warning("NAVIGUIDE_TEST_SKIP_SERVICE_CHECK ignoré hors pytest")
    return False


def assert_simulator_service_inactive() -> None:
    """Arrête la migration si naviguide-simulator est actif (systemctl is-active)."""
    if _service_check_skipped():
        return
    try:
        proc = subprocess.run(
            ["systemctl", "is-active", "--quiet", SERVICE_UNIT],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except FileNotFoundError:
        log.warning(
            "systemctl absent : impossible de vérifier que %s est arrêté",
            SERVICE_UNIT,
        )
        return
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(
            f"refus : systemctl is-active {SERVICE_UNIT} n'a pas répondu — migration annulée",
        ) from exc
    if proc.returncode == 0:
        raise SystemExit(
            f"refus : {SERVICE_UNIT} est actif — arrêtez le service avant la migration "
            f"(systemctl stop {SERVICE_UNIT})",
        )


@dataclass
class PearlAliasPlan:
    canonical: str
    source_key: str
    kind: str
    ts: float


def plan_pearl_alias_copies() -> list[PearlAliasPlan]:
    import pearl_store  # noqa: PLC0415
    from ici_engine import ensure_pearl_amp_layer_sig, thin_cache_key  # noqa: PLC0415

    ensure_pearl_amp_layer_sig("migrate_pearl_keys.plan")
    by_canonical: dict[str, PearlAliasPlan] = {}
    for key, row in pearl_store.iter_pearls():
        parsed = _coords_from_key(key)
        if not parsed:
            continue
        lat, lon, radius = parsed
        canonical = thin_cache_key(float(lat), float(lon), float(radius))
        if key == canonical or pearl_store.get_pearl(canonical):
            continue
        kind = str(row.get("kind") or "thin")
        ts = float(row.get("ts") or 0)
        prev = by_canonical.get(canonical)
        if prev is None or (prev.kind != "rich" and kind == "rich") or (
            prev.kind == kind and ts > prev.ts
        ):
            by_canonical[canonical] = PearlAliasPlan(
                canonical=canonical, source_key=key, kind=kind, ts=ts,
            )
    return sorted(by_canonical.values(), key=lambda plan: plan.canonical)


def run_pearl_alias_migration(*, dry_run: bool = True, skip_backup: bool = False) -> dict[str, Any]:
    import pearl_store  # noqa: PLC0415
    from ici_engine import amp_layer_sig, ensure_pearl_amp_layer_sig  # noqa: PLC0415

    assert_simulator_service_inactive()
    ensure_pearl_amp_layer_sig("migrate_pearl_keys")
    plans = plan_pearl_alias_copies()
    result: dict[str, Any] = {
        "dry_run": dry_run,
        "planned": len(plans),
        "inserted": 0,
        "backup": None,
    }
    zero_plans = [plan for plan in plans if plan.canonical.endswith(":a0")]
    if zero_plans:
        log.warning(
            "migration perles : %d copie(s) vers une clé :a0 annulée(s)",
            len(zero_plans),
        )
        print(
            f"  ATTENTION : {len(zero_plans)} copie(s) vers :a0 annulée(s) "
            f"(signature courante a{amp_layer_sig()})",
            flush=True,
        )
        plans = [plan for plan in plans if not plan.canonical.endswith(":a0")]
        result["planned"] = len(plans)
    if not plans:
        print("  perles : aucune copie canonique à faire", flush=True)
        return result
    print(
        f"  perles : {len(plans)} copie(s) canonique(s) à insérer (signature AMP a{amp_layer_sig()})",
        flush=True,
    )
    if dry_run:
        for plan in plans[:8]:
            print(f"    {plan.source_key} → {plan.canonical}", flush=True)
        if len(plans) > 8:
            print(f"    … +{len(plans) - 8}", flush=True)
        return result
    backup_path = None
    if not skip_backup:
        from restore_moments import require_live_backup  # noqa: PLC0415

        backup_path = require_live_backup()
        result["backup"] = str(backup_path)
    inserted = 0
    for plan in plans:
        src = pearl_store.get_pearl(plan.source_key)
        if not src or not isinstance(src.get("bag"), dict):
            continue
        coords = _coords_from_key(plan.source_key)
        lat = lon = None
        if coords:
            lat, lon = coords[0], coords[1]
        if pearl_store.insert_pearl_if_absent(
            plan.canonical,
            src["bag"],
            plan.kind,
            lat,
            lon,
            src.get("ts"),
        ):
            inserted += 1
    result["inserted"] = inserted
    print(f"  perles : {inserted} ligne(s) canonique(s) insérée(s)", flush=True)
    if backup_path is not None:
        print(f"  sauvegarde : {backup_path}", flush=True)
    return result
