"""Réancrage stock officiel : dry-run, sauvegarde, pas de perte de lignes moments."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import official_store
import pearl_store
import reanchor_official
from moment_journal import apply_moment_reanchor, merge_preserve_moment_rows, plan_moment_reanchor
from voyage_clock import OFFICIAL_VOYAGE_ID


@pytest.fixture
def isolated_reanchor_env(tmp_path, monkeypatch):
    store = tmp_path / "store"
    voyage = tmp_path / "voyage"
    store.mkdir()
    voyage.mkdir()
    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_STORE_DIR", str(store))
    monkeypatch.setenv("NAVIGUIDE_VOYAGE_DIR", str(voyage))
    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_WORKER", "0")
    official_store.reset_store()
    pearl_store.reset()
    yield store, voyage
    pearl_store.reset()
    official_store.reset_store()


def _seed_climo(_store: Path, marks: list[dict]) -> None:
    payload = {"clock": {"t0": "2026-05-15T08:00:00Z", "marks": marks, "vertices": []}}
    official_store.put("climo", payload, key="route:test:2026-05-15T08:00:00Z:2026-10-18")


def _seed_moments_sqlite(rows: list[dict]) -> None:
    pearl_store.replace_moments(OFFICIAL_VOYAGE_ID, rows)


def _grant_writes_after_backup(store_parent: Path) -> None:
    reanchor_official.reset_run_guards()
    reanchor_official.backup_store(backup_parent=store_parent)
    reanchor_official._writes_enabled = True  # noqa: SLF001 — garde-fou test


def _stub_refresh(monkeypatch) -> None:
    monkeypatch.setattr("official_store.refresh_family", lambda *a, **k: "unchanged")


def test_refuse_empty_store(tmp_path, monkeypatch):
    empty = tmp_path / "empty-store"
    empty.mkdir()
    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_STORE_DIR", str(empty))
    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_WORKER", "0")
    import official_store

    official_store.reset_store()
    reanchor_official.reset_run_guards()
    with pytest.raises(SystemExit, match="refus : stock officiel vide"):
        reanchor_official.refuse_empty_store()


def test_dry_run_writes_nothing(isolated_reanchor_env):
    store, _voyage = isolated_reanchor_env
    _seed_climo(store, [
        {"name": "Fort-de-France (Martinique)", "iso": "2026-09-01T00:00:00Z",
         "lat": -7.0, "lon": -118.0, "filmNm": 1000},
    ])
    _seed_moments_sqlite([
        {"seq": 1, "t": "2026-05-15T08:00:00Z", "signature": "a", "changes": [], "moment": {}, "pos": {}},
        {"seq": 2, "t": "2026-05-16T08:00:00Z", "signature": "b", "changes": [], "moment": {}, "pos": {}},
    ])
    climo_files = list(store.glob("*/climo.json"))
    assert climo_files
    climo = climo_files[0]
    before_mtime = climo.stat().st_mtime
    before_db = pearl_store.db_path().stat().st_mtime if pearl_store.db_path().is_file() else 0

    assert reanchor_official.run_reanchor(dry_run=True) == 0

    assert climo.stat().st_mtime == before_mtime
    if before_db:
        assert pearl_store.db_path().stat().st_mtime == before_db
    assert pearl_store.count_moments(OFFICIAL_VOYAGE_ID) == 2
    plan = reanchor_official.plan_reanchor()
    assert plan.counts_before.moment_rows == 2
    assert any("plan :" in line for line in plan.summary_lines())


def test_backup_creates_timestamped_copy(isolated_reanchor_env):
    store, _voyage = isolated_reanchor_env
    _seed_climo(store, [{"name": "La Rochelle", "iso": "2026-05-15T08:00:00Z", "lat": 46.15, "lon": -1.16}])
    _seed_moments_sqlite([
        {"seq": 0, "t": "2026-05-15T08:00:00Z", "signature": "s", "changes": [], "moment": {}, "pos": {}},
    ])
    dest = reanchor_official.backup_store(backup_parent=store.parent)
    assert dest.is_dir()
    manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.get("copied")
    assert (dest / "official-store").exists() or (dest / "naviguide.sqlite").exists()
    sqlite_meta = manifest.get("sqlite") or {}
    assert sqlite_meta.get("integrity") == "ok"
    assert sqlite_meta.get("counts", {}).get("moments") == 1


def test_sqlite_backup_api_coherent_under_wal(isolated_reanchor_env):
    """backup() + integrity_check : pas de copie shutil seule sur fichier -wal."""
    _voyage_dir = isolated_reanchor_env[1]
    _seed_moments_sqlite([
        {"seq": 1, "t": "2026-05-15T08:00:00Z", "signature": "a", "changes": [], "moment": {}, "pos": {}},
    ])
    src = pearl_store.db_path()
    conn = sqlite3.connect(str(src))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "INSERT INTO pearls (key, lat, lon, kind, bag, ts) VALUES (?, ?, ?, ?, ?, ?)",
        ("k1", 1.0, 2.0, "thin", "{}", 1.0),
    )
    conn.commit()
    conn.close()
    assert (src.parent / f"{src.name}-wal").is_file() or src.stat().st_size > 0

    dest = _voyage_dir / "backup-copy.sqlite"
    meta = pearl_store.backup_database(dest)
    assert meta["integrity"] == "ok"
    assert meta["counts"] == pearl_store.sqlite_table_counts(src)

    conn2 = sqlite3.connect(str(src))
    conn2.execute(
        "INSERT INTO pearls (key, lat, lon, kind, bag, ts) VALUES (?, ?, ?, ?, ?, ?)",
        ("k2", 3.0, 4.0, "thin", "{}", 2.0),
    )
    conn2.commit()
    conn2.close()
    backup_counts = pearl_store.sqlite_table_counts(dest)
    live_counts = pearl_store.sqlite_table_counts(src)
    assert backup_counts["pearls"] == 1
    assert live_counts["pearls"] == 2


def test_run_reanchor_backup_before_first_write(isolated_reanchor_env, monkeypatch):
    store, _voyage = isolated_reanchor_env
    _seed_climo(store, [
        {"name": "Fort-de-France (Martinique)", "iso": "2026-09-01T00:00:00Z",
         "lat": 14.6, "lon": -61.1, "filmNm": 1000},
    ])
    _seed_moments_sqlite([
        {"seq": 0, "t": "2026-05-15T08:00:00Z", "signature": "s", "changes": [], "moment": {}, "pos": {}},
    ])
    _stub_refresh(monkeypatch)
    clock = {"t0": "2026-05-15T08:00:00Z", "marks": [], "vertices": []}
    monkeypatch.setattr("voyage_store.load_voyage", lambda _vid: {"clock": clock})
    monkeypatch.setattr("moment_journal._build_rows", lambda _v, _y: [])

    order: list[str] = []
    real_backup = reanchor_official.backup_store

    def _track_backup(**kwargs):
        order.append("backup")
        return real_backup(**kwargs)

    real_put = official_store.put

    def _track_put(family, payload, key=None):
        order.append(f"put:{family}")
        return real_put(family, payload, key)

    monkeypatch.setattr(reanchor_official, "backup_store", _track_backup)
    monkeypatch.setattr(official_store, "put", _track_put)

    assert reanchor_official.run_reanchor() == 0
    assert order[0] == "backup"
    assert all(e == "backup" or e.startswith("put:") for e in order)
    if any(e.startswith("put:") for e in order):
        assert order.index("backup") < next(i for i, e in enumerate(order) if e.startswith("put:"))


def test_run_reanchor_full_counts_never_decrease(isolated_reanchor_env, monkeypatch):
    store, _voyage = isolated_reanchor_env
    _seed_climo(store, [{"name": "La Rochelle", "iso": "2026-05-15T08:00:00Z", "lat": 46.15, "lon": -1.16}])
    _seed_moments_sqlite([
        {"seq": i, "t": f"2026-05-{15 + i}T08:00:00Z", "signature": f"s{i}",
         "changes": [], "moment": {}, "pos": {}}
        for i in range(3)
    ])
    pearl_store.kv_put("test", "row", {"x": 1})
    before = reanchor_official.collect_counts()
    _stub_refresh(monkeypatch)
    monkeypatch.setattr(
        "voyage_store.load_voyage",
        lambda _vid: {"clock": {"t0": "2026-05-15T08:00:00Z", "marks": [], "vertices": []}},
    )
    monkeypatch.setattr("moment_journal._build_rows", lambda _v, _y: [])

    assert reanchor_official.run_reanchor() == 0
    after = reanchor_official.collect_counts()
    assert after.pearls >= before.pearls
    assert after.kv_rows >= before.kv_rows
    assert after.moment_rows >= before.moment_rows


def test_run_reanchor_idempotent_second_pass(isolated_reanchor_env, monkeypatch):
    store, _voyage = isolated_reanchor_env
    stamps = iter(("2026-10-18T100000Z", "2026-10-18T100001Z"))
    monkeypatch.setattr(reanchor_official, "_utc_stamp", lambda: next(stamps))
    _seed_climo(store, [{"name": "La Rochelle", "iso": "2026-05-15T08:00:00Z", "lat": 46.15, "lon": -1.16}])
    rows = [
        {"seq": i, "t": f"2026-05-{15 + i}T08:00:00Z", "signature": f"s{i}",
         "changes": [{"kind": "note", "id": f"n{i}"}], "moment": {}, "pos": {}}
        for i in range(4)
    ]
    _seed_moments_sqlite(rows)
    _stub_refresh(monkeypatch)
    monkeypatch.setattr(
        "voyage_store.load_voyage",
        lambda _vid: {"clock": {"t0": "2026-05-15T08:00:00Z", "marks": [], "vertices": []}},
    )
    monkeypatch.setattr("moment_journal._build_rows", lambda _v, _y: rows[:1])

    assert reanchor_official.run_reanchor() == 0
    db_after_first = pearl_store.db_path().read_bytes()
    climo_path = next(store.glob("*/climo.json"))
    climo_after_first = climo_path.read_text(encoding="utf-8")
    counts_first = reanchor_official.collect_counts()
    plan_second = reanchor_official.plan_reanchor()
    assert plan_second.marks_to_realign == 0

    assert reanchor_official.run_reanchor() == 0
    assert pearl_store.db_path().read_bytes() == db_after_first
    assert climo_path.read_text(encoding="utf-8") == climo_after_first
    counts_second = reanchor_official.collect_counts()
    assert counts_second.as_tuple() == counts_first.as_tuple()


def test_merge_preserves_rows_not_in_rebuild():
    existing = [
        {"seq": 1, "t": "2026-05-15T08:00:00Z", "signature": "a", "changes": [{"kind": "coast", "id": "c1", "tMs": 1}], "moment": {}},
        {"seq": 2, "t": "2026-05-16T08:00:00Z", "signature": "b", "changes": [], "moment": {}},
        {"seq": 3, "t": "2026-05-17T08:00:00Z", "signature": "c", "changes": [], "moment": {}},
    ]
    rebuilt = [
        {"seq": 1, "t": "2026-05-15T09:00:00Z", "signature": "a", "changes": [{"kind": "coast", "id": "c1", "tMs": 99}], "moment": {}},
    ]
    merged, kept = merge_preserve_moment_rows(existing, rebuilt)
    assert len(merged) == 3
    assert len(kept) == 2
    assert merged[0]["changes"][0]["tMs"] == 99
    assert {r["seq"] for r in merged} == {1, 2, 3}


def test_apply_moment_reanchor_never_drops_sqlite_rows(isolated_reanchor_env, monkeypatch):
    store, _voyage = isolated_reanchor_env
    _seed_climo(store, [{"name": "La Rochelle", "lat": 46.15, "lon": -1.16, "iso": "2026-05-15T08:00:00Z"}])
    rows = [
        {"seq": i, "t": f"2026-05-{10 + i}T08:00:00Z", "signature": f"s{i}",
         "changes": [{"kind": "note", "id": f"n{i}", "title": "t"}], "moment": {}, "pos": {}}
        for i in range(5)
    ]
    _seed_moments_sqlite(rows)

    def _thin_build(_vid, _voy):
        return [rows[0]]

    clock = {"t0": "2026-05-15T08:00:00Z", "marks": [], "vertices": []}
    monkeypatch.setattr("voyage_store.load_voyage", lambda _vid: {"clock": clock})
    monkeypatch.setattr("moment_journal._build_rows", _thin_build)
    _grant_writes_after_backup(store.parent)
    out = apply_moment_reanchor(dry_run=False)
    assert out["before"] == 5
    assert out["after"] == 5
    assert out["kept"] >= 4
    assert pearl_store.count_moments(OFFICIAL_VOYAGE_ID) == 5


def test_plan_moment_reanchor_reports_preserved_rows(isolated_reanchor_env, monkeypatch):
    store, _voyage = isolated_reanchor_env
    _seed_climo(store, [{"name": "La Rochelle", "lat": 46.15, "lon": -1.16, "iso": "2026-05-15T08:00:00Z"}])
    _seed_moments_sqlite([
        {"seq": 0, "t": "2026-05-15T08:00:00Z", "signature": "s", "changes": [], "moment": {}, "pos": {}},
        {"seq": 1, "t": "2026-05-16T08:00:00Z", "signature": "t", "changes": [], "moment": {}, "pos": {}},
    ])
    clock = {"t0": "2026-05-15T08:00:00Z", "marks": [], "vertices": []}
    monkeypatch.setattr("voyage_store.load_voyage", lambda _vid: {"clock": clock})
    monkeypatch.setattr("moment_journal._build_rows", lambda _v, _y: [])
    plan = plan_moment_reanchor()
    assert plan["merged_count"] == 2
    assert plan["kept_count"] == 2
