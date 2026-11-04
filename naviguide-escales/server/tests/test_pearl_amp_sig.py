"""Signature de couche pour les clés de perles : jamais a0 si une vraie signature existe."""
from __future__ import annotations

import importlib.util
import logging
import subprocess
import sys
from pathlib import Path

import pytest

import ici_engine
import official_store
import pearl_store
from ici_engine import (
    amp_layer_sig,
    ensure_pearl_amp_layer_sig,
    pearl_key_candidates,
    reset_caches,
    resolve_pearl_row,
    set_amp_layer_sig,
    thin_cache_key,
)


def _load_script(name: str):
    path = Path(__file__).resolve().parents[2] / "scripts" / name
    spec = importlib.util.spec_from_file_location(f"script_{name.replace('.py', '')}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_context_without_loaded_signature_never_uses_a0():
    pearl_store.reset()
    reset_caches()
    lat, lon = 46.14, -1.16
    base = f"{lat:.2f}:{lon:.2f}:30"
    pearl_store.put_pearl(f"{base}:rg3:a3769", {"zee": {"mrgid": 1}}, "rich", lat, lon, ts=10)
    pearl_store.put_pearl(f"{base}:am1a:a3776", {"zee": {"mrgid": 2}}, "rich", lat, lon, ts=20)
    reset_caches()
    assert amp_layer_sig() == "0"
    key = thin_cache_key(lat, lon, 30)
    assert ":a0" not in key
    assert key.endswith(":a3776")
    assert amp_layer_sig() == "3776"
    reset_caches()


def test_put_pearl_refuses_a0_when_real_sig_exists(caplog):
    pearl_store.reset()
    reset_caches()
    pearl_store.put_pearl("10.00:20.00:30:am1a:a0", {"zee": {"mrgid": 1}}, "thin", 10.0, 20.0)
    pearl_store.put_pearl("10.00:20.00:30:rg3:a3769", {"zee": {}}, "thin", 10.0, 20.0)
    with caplog.at_level(logging.WARNING, logger="naviguide-simulator.ici"):
        with pytest.raises(RuntimeError, match="a0"):
            pearl_store.put_pearl("11.00:21.00:30:am1a:a0", {"zee": {}}, "thin", 11.0, 21.0)
    assert pearl_store.get_pearl("11.00:21.00:30:am1a:a0") is None
    assert pearl_store.get_pearl("10.00:20.00:30:am1a:a0") is not None
    assert pearl_store.get_pearl("10.00:20.00:30:rg3:a3769") is not None
    assert any("a0" in record.message for record in caplog.records)
    reset_caches()


def test_pearl_key_candidates_order_current_then_am1a_rg3_naked():
    pearl_store.reset()
    reset_caches()
    set_amp_layer_sig("4000", ok=True)
    lat, lon = 1.02, 2.04
    base = f"{lat:.2f}:{lon:.2f}:30"
    pearl_store.put_pearl(f"{base}:am1a:a3769", {"zee": {"mrgid": 1}}, "thin", lat, lon, ts=100)
    pearl_store.put_pearl(f"{base}:am1a:a3776", {"zee": {"mrgid": 2}}, "rich", lat, lon, ts=300)
    pearl_store.put_pearl(f"{base}:am1a:a3500", {"zee": {"mrgid": 3}}, "rich", lat, lon, ts=400)
    pearl_store.put_pearl(f"{base}:rg3", {"zee": {"mrgid": 4}}, "thin", lat, lon, ts=50)
    pearl_store.put_pearl(f"{base}:rg3:a3769", {"zee": {"mrgid": 5}}, "thin", lat, lon, ts=250)
    pearl_store.put_pearl(base, {"zee": {"mrgid": 6}}, "thin", lat, lon, ts=10)
    pearl_store.put_pearl(f"{base}:legacy", {"zee": {"mrgid": 7}}, "thin", lat, lon, ts=5)
    keys = pearl_key_candidates(lat, lon, 30.0)
    assert keys == [
        f"{base}:am1a:a4000",
        f"{base}:am1a:a3500",
        f"{base}:am1a:a3776",
        f"{base}:am1a:a3769",
        f"{base}:rg3:a3769",
        f"{base}:rg3",
        base,
        f"{base}:legacy",
    ]
    row, hit = resolve_pearl_row(lat, lon, 30.0)
    assert hit == f"{base}:am1a:a3500"
    assert row["bag"]["zee"]["mrgid"] == 3
    reset_caches()


def test_pearl_key_candidates_rank_current_signature_first():
    pearl_store.reset()
    reset_caches()
    set_amp_layer_sig("3776", ok=True)
    lat, lon = 1.02, 2.04
    base = f"{lat:.2f}:{lon:.2f}:30"
    pearl_store.put_pearl(f"{base}:rg3", {"zee": {"mrgid": 1}}, "thin", lat, lon)
    pearl_store.put_pearl(f"{base}:am1a:a3769", {"zee": {"mrgid": 2}}, "rich", lat, lon)
    pearl_store.put_pearl(f"{base}:am1a:a3776", {"zee": {"mrgid": 3}}, "rich", lat, lon)
    keys = pearl_key_candidates(lat, lon, 30.0)
    assert keys[0].endswith(":a3776")
    row, hit = resolve_pearl_row(lat, lon, 30.0)
    assert hit.endswith(":a3776")
    assert row["bag"]["zee"]["mrgid"] == 3
    reset_caches()


def test_resolve_pearl_row_finds_legacy_rg3_key():
    pearl_store.reset()
    reset_caches()
    set_amp_layer_sig("3769", ok=True)
    lat, lon = 46.14, -1.16
    legacy = f"{lat:.2f}:{lon:.2f}:30:rg3"
    pearl_store.put_pearl(legacy, {"zee": {"mrgid": 1}, "sources": {"bi": "ok"}}, "rich", lat, lon)
    row, key = resolve_pearl_row(lat + 0.001, lon, 30.0)
    assert row is not None
    assert key == legacy
    assert row["bag"]["zee"]["mrgid"] == 1
    reset_caches()


def test_neighbor_within_1_5nm_is_read_only_and_a0_is_skipped():
    pearl_store.reset()
    reset_caches()
    pearl_store.put_pearl(
        "0.00:0.00:30:am1a:a0",
        {"zee": {"mrgid": 1}},
        "thin",
        0.0,
        0.0,
    )
    set_amp_layer_sig("3769", ok=True)
    pearl_store.put_pearl(
        "0.02:0.00:30:am1a:a3769",
        {"zee": {"mrgid": 2}},
        "rich",
        0.015,
        0.0,
    )
    before = pearl_store.count_pearls()["total"]
    row, key = resolve_pearl_row(0.0, 0.0, 30.0)
    assert key == "0.02:0.00:30:am1a:a3769"
    assert row["bag"]["zee"]["mrgid"] == 2
    assert pearl_store.count_pearls()["total"] == before
    assert pearl_store.get_pearl("0.00:0.00:30:am1a:a0") is not None
    assert resolve_pearl_row(0.05, 0.0, 30.0) == (None, None)
    reset_caches()


def test_ensure_amp_sig_loads_from_pearl_keys():
    pearl_store.reset()
    reset_caches()
    set_amp_layer_sig("0", ok=False)
    lat, lon = 46.14, -1.16
    pearl_store.put_pearl(
        f"{lat:.2f}:{lon:.2f}:30:rg3:a3769",
        {"zee": {"mrgid": 1}},
        "rich",
        lat,
        lon,
    )
    assert ensure_pearl_amp_layer_sig("pytest") == "3769"
    assert amp_layer_sig() == "3769"
    reset_caches()


def test_fill_scripts_load_signature_before_work(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(
        ici_engine,
        "ensure_pearl_amp_layer_sig",
        lambda context="": seen.append(context) or "3769",
    )
    monkeypatch.setattr(official_store, "refresh_missing", lambda **_kwargs: {"families": {}})
    prepare = _load_script("prepare_official_store.py")
    prepare.one_pass()
    assert seen[0] == "prepare_official_store"

    restore = _load_script("restore_moments.py")
    monkeypatch.setattr(
        sys,
        "argv",
        ["restore_moments.py", "--dry-run", "--source-sqlite", "/tmp/naviguide-missing-source.sqlite"],
    )
    with pytest.raises(FileNotFoundError):
        restore.main()
    assert "restore_moments" in seen

    reanchor = _load_script("reanchor_official_moments.py")
    monkeypatch.setattr(sys, "argv", ["reanchor_official_moments.py"])
    with pytest.raises(SystemExit):
        reanchor.main()
    assert "reanchor_official_moments" in seen


def test_migrate_refuses_while_simulator_active(monkeypatch):
    monkeypatch.delenv("NAVIGUIDE_TEST_SKIP_SERVICE_CHECK", raising=False)

    def fake_run(cmd, **kwargs):
        assert cmd[:3] == ["systemctl", "is-active", "--quiet"]
        assert "naviguide-simulator" in cmd
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    from migrate_pearl_keys import assert_simulator_service_inactive

    with pytest.raises(SystemExit, match="naviguide-simulator"):
        assert_simulator_service_inactive()
