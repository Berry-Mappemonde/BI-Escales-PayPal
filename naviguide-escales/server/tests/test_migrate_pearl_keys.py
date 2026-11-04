"""Migration ajout-seule des clés de perles."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import pearl_store
from ici_engine import reset_caches, resolve_pearl_row, set_amp_layer_sig, thin_cache_key
from migrate_pearl_keys import plan_pearl_alias_copies, run_pearl_alias_migration


def test_plan_pearl_alias_inserts_canonical_copy_only(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_TEST_SKIP_SERVICE_CHECK", "1")
    pearl_store.reset()
    reset_caches()
    set_amp_layer_sig("3769", ok=True)
    lat, lon = 10.02, 20.04
    legacy = f"{lat:.2f}:{lon:.2f}:30:rg3"
    pearl_store.put_pearl(legacy, {"zee": {"mrgid": 9}}, "rich", lat, lon)
    plans = plan_pearl_alias_copies()
    canonical = thin_cache_key(lat, lon, 30.0)
    assert canonical.endswith(":a3769")
    assert ":a0" not in canonical
    assert any(plan.canonical == canonical and plan.source_key == legacy for plan in plans)
    preview = run_pearl_alias_migration(dry_run=True, skip_backup=True)
    assert preview["inserted"] == 0
    assert pearl_store.get_pearl(canonical) is None
    done = run_pearl_alias_migration(dry_run=False, skip_backup=True)
    assert done["inserted"] == 1
    assert pearl_store.get_pearl(canonical) is not None
    assert pearl_store.get_pearl(legacy) is not None
    assert resolve_pearl_row(lat, lon, 30.0)[1] == canonical
    again = run_pearl_alias_migration(dry_run=False, skip_backup=True)
    assert again["inserted"] == 0
    assert again["planned"] == 0
    reset_caches()


def test_migrate_refuses_while_service_active_and_writes_nothing(monkeypatch):
    monkeypatch.delenv("NAVIGUIDE_TEST_SKIP_SERVICE_CHECK", raising=False)
    pearl_store.reset()
    reset_caches()
    set_amp_layer_sig("3769", ok=True)
    lat, lon = 12.02, 4.04
    legacy = f"{lat:.2f}:{lon:.2f}:30:rg3"
    pearl_store.put_pearl(legacy, {"zee": {"mrgid": 4}}, "rich", lat, lon)
    canonical = thin_cache_key(lat, lon, 30.0)

    def fake_run(cmd, **_kwargs):
        assert cmd[:3] == ["systemctl", "is-active", "--quiet"]
        assert "naviguide-simulator" in cmd
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SystemExit, match="naviguide-simulator"):
        run_pearl_alias_migration(dry_run=False, skip_backup=True)
    assert pearl_store.get_pearl(canonical) is None
    assert pearl_store.get_pearl(legacy) is not None
    reset_caches()


def test_migrate_backs_up_before_insert(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_TEST_SKIP_SERVICE_CHECK", "1")
    pearl_store.reset()
    reset_caches()
    set_amp_layer_sig("3776", ok=True)
    lat, lon = 8.02, -3.04
    legacy = f"{lat:.2f}:{lon:.2f}:30:rg3"
    pearl_store.put_pearl(legacy, {"zee": {"mrgid": 8}}, "thin", lat, lon)
    out = run_pearl_alias_migration(dry_run=False, skip_backup=False)
    assert out["inserted"] == 1
    assert out["backup"]
    backup = Path(out["backup"])
    assert backup.is_file()
    assert backup.name.startswith("naviguide.sqlite.restore-backup-")
    canonical = thin_cache_key(lat, lon, 30.0)
    assert canonical.endswith(":a3776")
    assert pearl_store.get_pearl(canonical) is not None
    assert pearl_store.get_pearl(legacy) is not None
    reset_caches()
