"""Restauration moments : backup, fusion, dry-run, idempotence."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import pearl_store
from restore_moments import (
    moment_row_key,
    plan_merge_moments,
    read_moments_from_sqlite,
    run_restore,
    validate_source_sqlite,
)
from voyage_clock import OFFICIAL_VOYAGE_ID


def _row(seq: int, t: str, sig: str = "s") -> dict:
    return {
        "voyageId": OFFICIAL_VOYAGE_ID,
        "seq": seq,
        "t": t,
        "signature": sig,
        "changes": [{"kind": "note", "title": "t", "fact": "f"}],
        "moment": {},
        "pos": {"lat": 1.0, "lon": 2.0},
    }


def _write_sqlite(path: Path, rows: list[dict]) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE moments ("
            "voyage_id TEXT, seq INTEGER, t TEXT, lat REAL, lon REAL, "
            "leg_idx INTEGER, signature TEXT, changes TEXT, moment TEXT, "
            "PRIMARY KEY (voyage_id, seq))"
        )
        for row in rows:
            pos = row.get("pos") or {}
            conn.execute(
                "INSERT INTO moments VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    row["voyageId"],
                    int(row["seq"]),
                    row.get("t"),
                    pos.get("lat"),
                    pos.get("lon"),
                    row.get("legIdx"),
                    row.get("signature"),
                    json.dumps(row.get("changes") or []),
                    json.dumps(row.get("moment") or {}),
                ),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def restore_env(tmp_path, monkeypatch):
    voyage = tmp_path / "voyage"
    store = tmp_path / "store"
    voyage.mkdir()
    store.mkdir()
    monkeypatch.setenv("NAVIGUIDE_VOYAGE_DIR", str(voyage))
    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_STORE_DIR", str(store))
    pearl_store.reset()
    yield tmp_path


def test_moment_row_key_stable():
    a = _row(0, "2026-05-15T08:00:00Z", "sig-a")
    b = {**a, "seq": 99}
    assert moment_row_key(a) == moment_row_key(b)


def test_plan_merge_inserts_missing_only():
    live = [_row(0, "2026-05-16T08:00:00Z", "only-live")]
    source = [_row(0, "2026-05-15T08:00:00Z", "from-backup"), _row(1, "2026-05-16T08:00:00Z", "only-live")]
    merged, plan = plan_merge_moments(live, source, voyage_id=OFFICIAL_VOYAGE_ID)
    assert plan.before == 1
    assert plan.to_insert == 1
    assert plan.after == 2
    assert len(merged) == 2
    keys = {moment_row_key(r) for r in merged}
    assert moment_row_key(source[0]) in keys


def test_plan_merge_refuses_count_drop():
    live = [_row(i, f"2026-05-{10 + i}T08:00:00Z", f"s{i}") for i in range(3)]
    empty: list[dict] = []
    merged, plan = plan_merge_moments(live, empty, voyage_id=OFFICIAL_VOYAGE_ID)
    assert plan.after == 3
    assert len(merged) == 3


def test_validate_source_sqlite_rejects_empty(tmp_path):
    p = tmp_path / "empty.sqlite"
    _write_sqlite(p, [])
    with pytest.raises(ValueError, match="sans moments"):
        validate_source_sqlite(p)


def test_run_restore_dry_run_and_idempotent(restore_env):
    tmp = restore_env
    live_db = pearl_store.db_path()
    source = tmp / "source.sqlite"
    backup_rows = [_row(i, f"2026-05-{10 + i}T08:00:00Z", f"b{i}") for i in range(5)]
    _write_sqlite(source, backup_rows)
    pearl_store.replace_moments(OFFICIAL_VOYAGE_ID, [_row(0, "2026-05-20T08:00:00Z", "live-only")])

    out = run_restore(source_sqlite=source, dry_run=True, skip_backup=True, refresh_store=False)
    assert out["plans"][OFFICIAL_VOYAGE_ID]["before"] == 1
    assert out["plans"][OFFICIAL_VOYAGE_ID]["to_insert"] == 5
    assert pearl_store.count_moments(OFFICIAL_VOYAGE_ID) == 1

    run_restore(source_sqlite=source, dry_run=False, skip_backup=True, refresh_store=False)
    assert pearl_store.count_moments(OFFICIAL_VOYAGE_ID) == 6

    second = run_restore(source_sqlite=source, dry_run=True, skip_backup=True, refresh_store=False)
    assert second["plans"][OFFICIAL_VOYAGE_ID]["to_insert"] == 0


def test_read_moments_from_sqlite_roundtrip(restore_env, tmp_path):
    src = tmp_path / "bak.sqlite"
    rows = [_row(i, f"2026-05-{10 + i}T08:00:00Z", f"x{i}") for i in range(4)]
    _write_sqlite(src, rows)
    loaded = read_moments_from_sqlite(src, OFFICIAL_VOYAGE_ID)[OFFICIAL_VOYAGE_ID]
    assert len(loaded) == 4
    assert loaded[0]["signature"] == "x0"


def test_run_restore_creates_live_backup_before_write(restore_env, tmp_path):
    source = tmp_path / "source.sqlite"
    _write_sqlite(source, [_row(0, "2026-05-15T08:00:00Z", "a")])
    pearl_store.replace_moments(OFFICIAL_VOYAGE_ID, [])
    out = run_restore(source_sqlite=source, dry_run=False, skip_backup=False, refresh_store=False)
    assert out.get("backup")
    assert Path(out["backup"]).is_file()
    assert pearl_store.count_moments(OFFICIAL_VOYAGE_ID) == 1
