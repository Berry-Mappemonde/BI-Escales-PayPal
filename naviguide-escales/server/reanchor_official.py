"""Réancrage RG10/RG14 du stock officiel — sans perte de lignes (perles / moments).

Utilisé par `scripts/reanchor_official_moments.py` et les tests pytest.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

FAMILIES_TOUCHED = ("climo", "moments", "film")

_backup_completed = False
_writes_enabled = False


def reset_run_guards() -> None:
    global _backup_completed, _writes_enabled
    _backup_completed = False
    _writes_enabled = False


def backup_was_completed() -> bool:
    return _backup_completed


def writes_enabled() -> bool:
    return _writes_enabled


def _require_backup_before_write() -> None:
    if _writes_enabled:
        return
    raise RuntimeError("écriture refusée : sauvegarde non effectuée")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


@dataclass
class StoreCounts:
    pearls: int = 0
    moment_rows: int = 0
    kv_rows: int = 0
    climo_files: int = 0
    moments_files: int = 0
    film_files: int = 0
    clock_marks: int = 0

    def as_tuple(self) -> tuple[int, int, int]:
        return (self.pearls, self.kv_rows, self.moment_rows)


@dataclass
class ReanchorPlan:
    counts_before: StoreCounts
    marks_to_realign: int = 0
    moment_rows_after_merge: int = 0
    rows_kept_instead_of_drop: int = 0
    film_keys_to_refresh: int = 0
    would_touch_paths: list[str] = field(default_factory=list)
    kept_row_seqs: list[int] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        b = self.counts_before
        lines = [
            f"avant : perles={b.pearls} moments_sqlite={b.moment_rows} kv={b.kv_rows} "
            f"marques_horloge={b.clock_marks} fichiers(climo/moments/film)="
            f"{b.climo_files}/{b.moments_files}/{b.film_files}",
            f"plan : marques_recollées={self.marks_to_realign} "
            f"moments_après_fusion={self.moment_rows_after_merge} "
            f"lignes_préservées(évitent_suppression)={self.rows_kept_instead_of_drop} "
            f"film_à_régénérer={self.film_keys_to_refresh}",
        ]
        if self.kept_row_seqs:
            preview = self.kept_row_seqs[:12]
            extra = "" if len(self.kept_row_seqs) <= 12 else f" … +{len(self.kept_row_seqs) - 12}"
            lines.append(f"seq conservées (absentes du recalcul) : {preview}{extra}")
        return lines


def store_looks_live(counts: StoreCounts, root: Path) -> bool:
    """Vrai si le stock ressemble à une prod/poste peuplé (pas un chemin vide par erreur)."""
    if counts.pearls > 0 or counts.kv_rows > 0 or counts.moment_rows > 0:
        return True
    if counts.clock_marks > 0:
        return True
    if counts.climo_files or counts.moments_files or counts.film_files:
        return True
    if root.is_dir() and any(root.glob("*/climo.json")):
        return True
    return False


def refuse_empty_store() -> None:
    """Bloque si NAVIGUIDE_OFFICIAL_STORE_DIR pointe vers un dossier vide ou absent."""
    import official_store

    root = official_store.disk_root()
    counts = collect_counts()
    if store_looks_live(counts, root):
        return
    msg = (
        f"refus : stock officiel vide ou inexistant ({root}).\n"
        "Sur OVH, sans variable, le serveur utilise "
        "naviguide-simulator/server/voyage_data/official-store — ne pas viser "
        "~/.cache/naviguide/voyage-store (absent en prod).\n"
        "Vérifiez NAVIGUIDE_OFFICIAL_STORE_DIR dans ~/.config/naviguide/simulator.env."
    )
    raise SystemExit(msg)


def collect_counts() -> StoreCounts:
    import official_store
    import pearl_store

    counts = StoreCounts()
    try:
        info = pearl_store.count_pearls() or {}
        counts.pearls = int(info.get("rich") or 0) + int(info.get("thin") or 0)
    except Exception:
        counts.pearls = 0
    try:
        from voyage_clock import OFFICIAL_VOYAGE_ID  # noqa: PLC0415

        counts.moment_rows = int(pearl_store.count_moments(OFFICIAL_VOYAGE_ID) or 0)
    except Exception:
        counts.moment_rows = 0
    counts.kv_rows = pearl_store.count_kv_rows()

    root = official_store.disk_root()
    if root.is_dir():
        counts.climo_files = len(list(root.glob("*/climo.json")))
        counts.moments_files = len(list(root.glob("*/moments.json")))
        counts.film_files = len(list(root.glob("*/film.json")))

    clock = official_store.stored_clock() or {}
    counts.clock_marks = len(clock.get("marks") or [])
    return counts


def _family_paths(root: Path, family: str) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(p for p in root.glob(f"*/{family}.json") if p.is_file())


def paths_touched() -> list[Path]:
    import official_store
    import pearl_store

    out: list[Path] = []
    root = official_store.disk_root()
    for fam in FAMILIES_TOUCHED:
        out.extend(_family_paths(root, fam))
    try:
        db = pearl_store.db_path()
        if db.is_file():
            out.append(db)
    except Exception:
        pass
    return out


def _align_marks_on_clock(clock: dict) -> tuple[dict, int]:
    from film_script import _align_quay_stop_to_passage  # noqa: PLC0415

    marks = list(clock.get("marks") or [])
    if not marks:
        return clock, 0
    aligned = [_align_quay_stop_to_passage(m, clock) for m in marks]
    n = sum(1 for a, b in zip(aligned, marks) if a != b)
    if n == 0:
        return clock, 0
    return {**clock, "marks": aligned}, n


def _climo_payload_and_clock() -> tuple[Optional[dict], Optional[dict], Optional[str]]:
    import official_store

    hit = official_store.get("climo")
    if not isinstance(hit, dict):
        return None, None, None
    key = str(hit.get("key") or "")
    payload = hit.get("payload") if isinstance(hit.get("payload"), dict) else hit
    if not isinstance(payload, dict):
        return None, None, key
    clock = payload.get("clock") if isinstance(payload.get("clock"), dict) else payload
    if not isinstance(clock, dict):
        return None, None, key
    return payload, clock, key


def plan_reanchor() -> ReanchorPlan:
    import official_store

    before = collect_counts()
    plan = ReanchorPlan(counts_before=before)
    plan.would_touch_paths = [str(p) for p in paths_touched()]

    payload, clock, _key = _climo_payload_and_clock()
    if clock:
        _, n = _align_marks_on_clock(clock)
        plan.marks_to_realign = n

    from moment_journal import plan_moment_reanchor  # noqa: PLC0415

    mplan = plan_moment_reanchor()
    plan.moment_rows_after_merge = mplan["merged_count"]
    plan.rows_kept_instead_of_drop = mplan["kept_count"]
    plan.kept_row_seqs = list(mplan.get("kept_seqs") or [])

    st = official_store.get_store()
    try:
        plan.film_keys_to_refresh = 1 if st.family_key("film") else 0
    except Exception:
        plan.film_keys_to_refresh = 1
    return plan


def backup_store(backup_parent: Optional[Path] = None) -> Path:
    """Copie horodatée à côté du stock (fichiers + sqlite via backup())."""
    global _backup_completed
    import official_store
    import pearl_store

    root = official_store.disk_root()
    parent = backup_parent or root.parent
    dest = parent / f"{root.name}-reanchor-backup-{_utc_stamp()}"
    dest.mkdir(parents=True, exist_ok=False)

    copied: list[str] = []
    sqlite_meta: dict[str, Any] = {}
    for fam in FAMILIES_TOUCHED:
        for src in _family_paths(root, fam):
            rel = src.relative_to(root)
            tgt = dest / "official-store" / rel
            tgt.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, tgt)
            copied.append(str(tgt))

    db = pearl_store.db_path()
    if db.is_file():
        tgt_db = dest / "naviguide.sqlite"
        sqlite_meta = pearl_store.backup_database(tgt_db)
        copied.append(str(tgt_db))
        print(
            f"  backup sqlite : integrity={sqlite_meta.get('integrity')} counts={sqlite_meta.get('counts')}",
            flush=True,
        )

    import os

    url = (os.environ.get("SIMULATOR_MONGO_URL") or "").strip()
    if url:
        _backup_mongo(dest, copied)

    manifest = {"copied": copied, "store_root": str(root), "sqlite": sqlite_meta}
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for line in copied:
        print(f"  backup : {line}", flush=True)
    print(f"backup : {dest}", flush=True)
    _backup_completed = True
    return dest


def _backup_mongo(dest: Path, copied: list[str]) -> None:
    import official_store

    st = official_store.get_store()
    lister = getattr(st.backend, "list_family", None)
    if not callable(lister):
        return
    mongo_dir = dest / "mongo"
    mongo_dir.mkdir(parents=True, exist_ok=True)
    for family in FAMILIES_TOUCHED:
        rows = lister(family)
        out = mongo_dir / f"{family}.json"
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        copied.append(str(out))


def apply_climo_mark_realign(dry_run: bool) -> int:
    import official_store

    payload, clock, key = _climo_payload_and_clock()
    if not clock or not payload:
        print("  climo : absent", flush=True)
        return 0
    new_clock, n = _align_marks_on_clock(clock)
    if n == 0:
        print("  climo : marques déjà cohérentes", flush=True)
        return 0
    if dry_run:
        print(f"  climo : {n} marque(s) seraient recollées", flush=True)
        return n
    _require_backup_before_write()
    if "clock" in payload:
        payload = {**payload, "clock": new_clock}
    else:
        payload = new_clock
    official_store.put("climo", payload, key or None)
    print(f"  climo : {n} marque(s) recollée(s)", flush=True)
    return n


def _assert_counts_monotonic(before: StoreCounts, after: StoreCounts) -> None:
    if after.pearls < before.pearls:
        raise RuntimeError(f"perles perdues : {before.pearls} → {after.pearls}")
    if after.kv_rows < before.kv_rows:
        raise RuntimeError(f"lignes kv perdues : {before.kv_rows} → {after.kv_rows}")
    if after.moment_rows < before.moment_rows:
        raise RuntimeError(f"moments perdus : {before.moment_rows} → {after.moment_rows}")


def run_reanchor(
    *,
    dry_run: bool = False,
    skip_backup: bool = False,
) -> int:
    """Réancrage complet. Idempotent si les données sont déjà à jour."""
    global _writes_enabled
    import official_store
    from moment_journal import apply_moment_reanchor  # noqa: PLC0415

    reset_run_guards()
    official_store.reset_store()
    refuse_empty_store()
    root = official_store.disk_root()
    print(f"stock : {root}", flush=True)

    before = collect_counts()
    plan = plan_reanchor()
    for line in plan.summary_lines():
        print(line, flush=True)

    if dry_run:
        print("mode : --dry-run (aucune écriture)", flush=True)
        return 0

    if skip_backup:
        print(
            "ATTENTION : exécution sans sauvegarde (--i-accept-data-risk-without-backup)",
            flush=True,
        )
        global _backup_completed
        _backup_completed = True
    else:
        backup_store()
    _writes_enabled = True

    import official_store as _os

    _orig_put = _os.put

    def _guarded_put(family: str, payload: dict, key: Optional[str] = None) -> dict:
        _require_backup_before_write()
        return _orig_put(family, payload, key)

    _os.put = _guarded_put  # type: ignore[method-assign]
    try:
        apply_climo_mark_realign(dry_run=False)
        mid = collect_counts()
        _assert_counts_monotonic(before, mid)
        apply_moment_reanchor(dry_run=False)

        for family in ("moments", "film"):
            _require_backup_before_write()
            status = official_store.refresh_family(
                family,
                force=True,
                compute=_compute_moments_reanchor if family == "moments" else None,
            )
            print(f"  {family} : {status}", flush=True)
    finally:
        _os.put = _orig_put  # type: ignore[method-assign]

    after = collect_counts()
    print(
        f"après : perles={after.pearls} moments_sqlite={after.moment_rows} kv={after.kv_rows} "
        f"marques_horloge={after.clock_marks}",
        flush=True,
    )
    _assert_counts_monotonic(before, after)
    return 0


def _compute_moments_reanchor(voy: dict, now: datetime) -> Optional[dict]:
    """Rafraîchit le JSON moments depuis le sqlite sans relancer warm_moments."""
    import voyage_journal as journal  # noqa: PLC0415
    from moment_journal import read_moments  # noqa: PLC0415
    from official_store import journal_degraded  # noqa: PLC0415
    from voyage_clock import OFFICIAL_VOYAGE_ID  # noqa: PLC0415

    if not voy.get("clock"):
        return None
    journal.tick(voy, now, force=True)
    summary = journal.summary(500)
    days = {}
    for row in summary.get("days") or []:
        day = row.get("day")
        if day:
            try:
                days[day] = journal.read_day(day)
            except Exception:
                days[day] = []
    moments = read_moments(OFFICIAL_VOYAGE_ID)
    if not moments:
        return None
    if moments and not any(m.get("t") for m in moments):
        return None
    if journal_degraded(summary):
        return None
    return {"moments": moments, "journal": summary, "journal_days": days}
