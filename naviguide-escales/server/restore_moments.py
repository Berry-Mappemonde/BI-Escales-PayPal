"""Restauration du journal moments (sqlite + stock JSON) sans perte de lignes live."""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from moment_journal import moment_row_key

log = logging.getLogger("naviguide-simulator.restore_moments")


def _parse_moment_row(voyage_id: str, seq: int, t, lat, lon, leg_idx, sig, changes, moment) -> dict | None:
    try:
        return {
            "voyageId": voyage_id,
            "seq": int(seq),
            "t": t,
            "pos": {"lat": lat, "lon": lon},
            "legIdx": leg_idx,
            "signature": str(sig or ""),
            "changes": json.loads(changes) if isinstance(changes, str) else (changes or []),
            "moment": json.loads(moment) if isinstance(moment, str) else (moment or {}),
        }
    except Exception:
        return None


def read_moments_from_sqlite(path: Path, voyage_id: str | None = None) -> dict[str, list[dict]]:
    """Lit tous les voyages (ou un seul) depuis un fichier sqlite."""
    p = Path(path)
    if not p.is_file() or p.stat().st_size < 512:
        raise FileNotFoundError(f"sqlite source absent ou vide : {p}")
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        if str(row[0] if row else "").lower() != "ok":
            raise RuntimeError(f"sqlite source : integrity_check={row!r}")
        if voyage_id:
            voyages = [voyage_id]
        else:
            voyages = [
                str(r[0])
                for r in conn.execute("SELECT DISTINCT voyage_id FROM moments ORDER BY voyage_id").fetchall()
            ]
        out: dict[str, list[dict]] = {}
        for vid in voyages:
            rows = conn.execute(
                "SELECT seq, t, lat, lon, leg_idx, signature, changes, moment "
                "FROM moments WHERE voyage_id = ? ORDER BY seq",
                (vid,),
            ).fetchall()
            parsed: list[dict] = []
            for seq, t, lat, lon, leg_idx, sig, changes, moment in rows:
                row = _parse_moment_row(vid, seq, t, lat, lon, leg_idx, sig, changes, moment)
                if row:
                    parsed.append(row)
            out[vid] = parsed
        return out
    finally:
        conn.close()


def read_moments_from_json(path: Path, voyage_id: str | None = None) -> list[dict]:
    """Extrait `moments` d'un moments.json de stock."""
    p = Path(path)
    if not p.is_file() or p.stat().st_size < 2:
        raise FileNotFoundError(f"moments.json absent ou vide : {p}")
    body = json.loads(p.read_text(encoding="utf-8"))
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else body
    rows = list(payload.get("moments") or [])
    if voyage_id:
        rows = [r for r in rows if isinstance(r, dict) and str(r.get("voyageId") or voyage_id) == voyage_id]
    return [r for r in rows if isinstance(r, dict)]


def _sort_rows(rows: list[dict]) -> list[dict]:
    def key(row: dict) -> tuple:
        t = str(row.get("t") or "")
        return (t, int(row.get("seq") or 0), moment_row_key(row))

    return sorted(rows, key=key)


def _reseq(rows: list[dict], voyage_id: str) -> list[dict]:
    out: list[dict] = []
    for idx, row in enumerate(_sort_rows(rows)):
        out.append({**row, "voyageId": voyage_id, "seq": idx})
    return out


@dataclass
class VoyageRestorePlan:
    voyage_id: str
    before: int = 0
    after: int = 0
    to_insert: int = 0
    inserted_keys: list[str] = field(default_factory=list)


def plan_merge_moments(
    live_rows: list[dict],
    *source_batches: Iterable[dict],
    voyage_id: str | None = None,
) -> tuple[list[dict], VoyageRestorePlan]:
    """Fusionne les sources dans le live : ajoute les clés absentes, ne remplace jamais le live."""
    vid = voyage_id or str((live_rows[0] if live_rows else {}).get("voyageId") or "")
    for batch in source_batches:
        for row in batch:
            if isinstance(row, dict) and row.get("voyageId"):
                vid = vid or str(row["voyageId"])
                break
    live_by_key = {moment_row_key(r): r for r in live_rows if isinstance(r, dict)}
    before = len(live_by_key)
    inserts: list[dict] = []
    seen_insert: set[str] = set()
    for batch in source_batches:
        for row in batch:
            if not isinstance(row, dict):
                continue
            k = moment_row_key(row)
            if k in live_by_key or k in seen_insert:
                continue
            seen_insert.add(k)
            inserts.append(dict(row))
    merged = _reseq(list(live_by_key.values()) + inserts, vid or str(inserts[0].get("voyageId") or ""))
    plan = VoyageRestorePlan(
        voyage_id=vid,
        before=before,
        after=len(merged),
        to_insert=len(inserts),
        inserted_keys=list(seen_insert),
    )
    if plan.after < plan.before:
        raise RuntimeError(f"restauration {vid} : {plan.before} → {plan.after} (perte interdite)")
    return merged, plan


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def require_live_backup() -> Path:
    """Sauvegarde horodatée du sqlite live avant toute écriture."""
    import pearl_store  # noqa: PLC0415

    live = pearl_store.db_path()
    if not live.is_file():
        raise FileNotFoundError(f"sqlite live absent : {live}")
    dest = live.parent / f"naviguide.sqlite.restore-backup-{_utc_stamp()}"
    meta = pearl_store.backup_database(dest)
    log.info("backup live : %s integrity=%s", dest, meta.get("integrity"))
    return dest


def validate_source_sqlite(path: Path) -> Path:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"sqlite source introuvable : {p}")
    if p.stat().st_size < 512:
        raise ValueError(f"sqlite source vide : {p}")
    counts = pearl_store_sqlite_moment_count(p)
    if counts <= 0:
        raise ValueError(f"sqlite source sans moments : {p}")
    return p


def pearl_store_sqlite_moment_count(path: Path) -> int:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT COUNT(*) FROM moments").fetchone()
        return int((row[0] if row else 0) or 0)
    finally:
        conn.close()


def collect_json_sources(paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for p in paths:
        try:
            rows.extend(read_moments_from_json(p))
        except FileNotFoundError:
            continue
    return rows


def run_restore(
    *,
    source_sqlite: Path,
    json_paths: list[Path] | None = None,
    voyage_id: str | None = None,
    dry_run: bool = False,
    skip_backup: bool = False,
    refresh_store: bool = True,
) -> dict[str, Any]:
    """Restaure les moments manquants depuis backup sqlite (+ JSON optionnels)."""
    import pearl_store  # noqa: PLC0415
    from voyage_clock import OFFICIAL_VOYAGE_ID  # noqa: PLC0415

    vid = voyage_id or OFFICIAL_VOYAGE_ID
    try:
        from ici_engine import ensure_pearl_amp_layer_sig  # noqa: PLC0415

        ensure_pearl_amp_layer_sig("restore_moments")
    except Exception as exc:
        log.warning("restauration : signature de couche indisponible (%s)", exc)
    src = validate_source_sqlite(source_sqlite)
    backup_path: Path | None = None
    if not dry_run and not skip_backup:
        backup_path = require_live_backup()

    live_rows = pearl_store.list_moments(vid)
    source_rows = read_moments_from_sqlite(src, vid).get(vid) or []
    json_rows = collect_json_sources(json_paths or [])
    merged, plan = plan_merge_moments(live_rows, source_rows, json_rows, voyage_id=vid)

    result: dict[str, Any] = {
        "voyageId": vid,
        "dry_run": dry_run,
        "backup": str(backup_path) if backup_path else None,
        "source_sqlite": str(src),
        "plans": {
            vid: {
                "before": plan.before,
                "after": plan.after,
                "to_insert": plan.to_insert,
            },
        },
    }
    print(
        f"  {vid} : avant={plan.before} après={plan.after} à_insérer={plan.to_insert}",
        flush=True,
    )
    if dry_run:
        return result

    if plan.to_insert <= 0:
        print("  rien à insérer (déjà à jour)", flush=True)
        return result

    n = pearl_store.replace_moments(vid, merged)
    if n < plan.before:
        raise RuntimeError(f"sqlite live : {plan.before} → {n} après restauration")
    result["written"] = n

    if refresh_store:
        import official_store  # noqa: PLC0415
        from datetime import datetime as _dt  # noqa: PLC0415

        from moment_journal import read_moments  # noqa: PLC0415
        from reanchor_official import _compute_moments_reanchor  # noqa: PLC0415

        official_store.reset_store()
        from voyage_store import load_voyage  # noqa: PLC0415

        voy = load_voyage(vid)
        if voy:
            official_store.refresh_family(
                "moments",
                force=True,
                compute=_compute_moments_reanchor,
                now=_dt.now(timezone.utc),
            )
            official_store.refresh_family("film", force=True, now=_dt.now(timezone.utc))
        result["store_moments"] = len(read_moments(vid))
    return result
