"""Passage unique des perles : estimation, verrou, reprise, ajout seul."""
from __future__ import annotations

import json
import os
import threading

import pytest
from fastapi.testclient import TestClient

import ici_warm
import pearl_store
import pearls_warm
from ici_engine import _pearl_cell, reset_caches, set_amp_layer_sig, thin_cache_key
from voyage_clock import OFFICIAL_VOYAGE_ID
from voyage_store import save_voyage


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(pearls_warm.ENV_DIR, str(tmp_path / "one-shot"))
    monkeypatch.setenv(pearls_warm.ENV_FLOOR, "0")
    monkeypatch.setenv(pearls_warm.ENV_MEMORY, str(8 * 1024**3))
    monkeypatch.setattr(pearls_warm, "memory_bytes", lambda: 1024 * 1024)
    reset_caches()
    set_amp_layer_sig("3769", ok=True)
    yield


def _bag():
    return {"amp": [], "zee": None, "sources": {"bi": "ok"}, "pearl": "rich"}


def _save_route(n=6):
    points = [
        {"lat": 0.0, "lon": i * 0.4, "cumNm": i * 20.0}
        for i in range(n)
    ]
    save_voyage({
        "voyageId": OFFICIAL_VOYAGE_ID,
        "points": points,
        "marks": [],
        "t0": "2026-05-15T08:00:00Z",
    })


def _seed_valid(pearl, key=None):
    dest = key or thin_cache_key(pearl["lat"], pearl["lon"], 30.0)
    assert pearl_store.put_pearl(dest, _bag(), "rich", pearl["lat"], pearl["lon"])
    return dest


def test_estimate_measures_sample_and_writes_nothing(monkeypatch):
    _save_route(24)
    calls = {"n": 0}
    seen = {"n": 0}

    def mem():
        seen["n"] += 1
        return 100 if seen["n"] == 1 else 180

    def fill(_pearl):
        calls["n"] += 1
        return _bag()

    monkeypatch.setattr(pearls_warm, "memory_bytes", mem)
    before = pearl_store.count_pearls()["total"]
    moments = pearl_store.count_moments(OFFICIAL_VOYAGE_ID)
    root = os.environ[pearls_warm.ENV_DIR]
    est = pearls_warm.estimate(fill=fill)
    assert not os.path.exists(root)
    assert pearl_store.count_pearls()["total"] == before
    assert pearl_store.count_moments(OFFICIAL_VOYAGE_ID) == moments
    assert est["toCompute"] >= 20
    assert est["sample"] == 20
    assert calls["n"] == 20
    assert est["sampleRssBytes"] == 80
    assert est["sampleSeconds"] >= 0
    again = pearls_warm.estimate(fill=fill)
    assert again["fingerprint"] == est["fingerprint"]
    assert pearl_store.count_pearls()["total"] == before


def test_second_run_while_the_first_holds_the_lock_is_refused():
    _save_route(1)
    entered = threading.Event()
    release = threading.Event()

    def fill(_pearl):
        entered.set()
        assert release.wait(5)
        return _bag()

    outcomes = []

    def first():
        try:
            pearls_warm.run(fill=fill)
            outcomes.append("ok")
        except Exception as exc:
            outcomes.append(type(exc).__name__)
            release.set()

    def second():
        assert entered.wait(5)
        try:
            pearls_warm.run(fill=fill)
            outcomes.append("second-ok")
        except pearls_warm.Refused as exc:
            outcomes.append(exc.code)
        finally:
            release.set()

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert [thread.is_alive() for thread in threads] == [False, False]
    assert sorted(outcomes) == ["busy", "ok"]


def test_resume_after_a_simulated_stop_does_not_recompute(monkeypatch):
    _save_route(8)
    pearls = pearls_warm.inventory()
    assert len(pearls) >= 4
    filled = []
    phase = {"stop": True}

    def mem():
        if phase["stop"] and len(filled) >= 2:
            return 10**15
        return 1

    def fill(pearl):
        filled.append(pearl["id"])
        return _bag()

    monkeypatch.setattr(pearls_warm, "memory_bytes", mem)
    monkeypatch.setenv(pearls_warm.ENV_MEMORY, "1000")
    with pytest.raises(pearls_warm.Stopped) as stopped:
        pearls_warm.run(fill=fill)
    assert stopped.value.code == "memory"
    assert len(filled) == 2
    assert pearls_warm.public_status()["state"] == "stopped"
    assert not (pearls_warm._job_dir(mkdir=False) / ".done").is_file()
    phase["stop"] = False
    result = pearls_warm.run(fill=fill)
    assert filled == [pearl["id"] for pearl in pearls]
    assert result["found"] == result["routePoints"] == len(pearls)
    assert pearls_warm.public_status()["state"] == "done"


def test_cached_pearls_are_not_computed_and_a_second_pass_is_refused():
    _save_route(4)
    pearls = pearls_warm.inventory()
    assert pearls
    calls = {"n": 0}

    def fill(_pearl):
        calls["n"] += 1
        return _bag()

    for index, pearl in enumerate(pearls):
        la, lo = _pearl_cell(pearl["lat"], pearl["lon"])
        legacy = f"{la:.2f}:{lo:.2f}:30:am1a" if index % 2 == 0 else f"{la:.2f}:{lo:.2f}:30"
        _seed_valid(pearl, legacy)
    before = {
        pearl["id"]: pearl_store.get_pearl(
            f"{_pearl_cell(pearl['lat'], pearl['lon'])[0]:.2f}:{_pearl_cell(pearl['lat'], pearl['lon'])[1]:.2f}:30:am1a"
            if index % 2 == 0
            else f"{_pearl_cell(pearl['lat'], pearl['lon'])[0]:.2f}:{_pearl_cell(pearl['lat'], pearl['lon'])[1]:.2f}:30"
        )
        for index, pearl in enumerate(pearls)
    }
    result = pearls_warm.run(fill=fill)
    assert calls["n"] == 0
    assert result["done"] == 0
    assert result["skipped"] == len(pearls)
    assert result["found"] == len(pearls)
    for index, pearl in enumerate(pearls):
        assert pearl_store.get_pearl(thin_cache_key(pearl["lat"], pearl["lon"], 30.0)) is None
        assert pearl_store.get_pearl(
            f"{_pearl_cell(pearl['lat'], pearl['lon'])[0]:.2f}:{_pearl_cell(pearl['lat'], pearl['lon'])[1]:.2f}:30:am1a"
            if index % 2 == 0
            else f"{_pearl_cell(pearl['lat'], pearl['lon'])[0]:.2f}:{_pearl_cell(pearl['lat'], pearl['lon'])[1]:.2f}:30"
        ) == before[pearl["id"]]
    with pytest.raises(pearls_warm.Refused) as refused:
        pearls_warm.run(fill=fill)
    assert refused.value.code == "done"
    assert calls["n"] == 0


def test_a_valid_pearl_is_never_rewritten():
    _save_route(1)
    pearl = pearls_warm.inventory()[0]
    key = _seed_valid(pearl)
    before = pearl_store.get_pearl(key)

    def fill(_pearl):
        raise AssertionError("calcul")

    result = pearls_warm.run(fill=fill)
    assert result["done"] == 0
    assert pearl_store.get_pearl(key) == before


def test_a_falling_count_is_refused(monkeypatch):
    _save_route(1)
    pearl = pearls_warm.inventory()[0]
    key = _seed_valid(pearl)
    before = pearl_store.get_pearl(key)
    real = pearls_warm.counts
    seen = {"n": 0}

    def fake():
        seen["n"] += 1
        base = real()
        if seen["n"] > 1:
            return {"pearls": base["pearls"] - 1, "moments": base["moments"]}
        return base

    monkeypatch.setattr(pearls_warm, "counts", fake)

    def boom(_key):
        raise AssertionError("suppression")

    monkeypatch.setattr(pearl_store, "delete_pearl", boom)
    with pytest.raises(pearls_warm.Refused) as refused:
        pearls_warm.run(fill=lambda _pearl: _bag())
    assert refused.value.code == "count-down"
    assert "baisse" in str(refused.value)
    assert pearl_store.get_pearl(key) == before


def test_background_warmer_stays_off(monkeypatch):
    _save_route(1)
    calls = []
    monkeypatch.setattr(ici_warm, "start_background", lambda *_a, **_k: calls.append("start"))
    monkeypatch.setattr(ici_warm, "warm_official_route", lambda *_a, **_k: calls.append("loop"))
    assert ici_warm.warm_enabled() is False
    pearls_warm.run(fill=lambda _pearl: _bag())
    assert calls == []
    assert ici_warm.warm_enabled() is False
    assert os.environ.get("NAVIGUIDE_ICI_WARM") == "0"


def test_memory_at_the_cap_stops_cleanly_before_any_write(monkeypatch):
    _save_route(2)
    monkeypatch.setenv(pearls_warm.ENV_MEMORY, "1000")
    monkeypatch.setattr(pearls_warm, "memory_bytes", lambda: 5000)
    calls = {"n": 0}

    def fill(_pearl):
        calls["n"] += 1
        return _bag()

    with pytest.raises(pearls_warm.Stopped) as stopped:
        pearls_warm.run(fill=fill)
    assert stopped.value.code == "memory"
    assert calls["n"] == 0
    assert pearl_store.count_pearls()["total"] == 0
    status = pearls_warm.public_status()
    assert status["state"] == "stopped"
    assert status["lastError"]
    assert "/" not in status["lastError"]
    assert not (pearls_warm._job_dir(mkdir=False) / ".done").is_file()
    code = pearls_warm.main(["--run"])
    assert code == 3


def test_llm_pearl_is_skipped_and_counted_apart():
    _save_route(1)

    def fill(pearl):
        import llm_budget
        llm_budget.record("write", 10, 10)
        return _bag()

    before = llm_budget_tokens()
    with pytest.raises(pearls_warm.Failed) as failed:
        pearls_warm.run(fill=fill)
    assert "perles trouvées" in str(failed.value)
    status = pearls_warm.public_status()
    assert status["llmSkipped"] == 1
    assert status["done"] == 0
    assert status["state"] == "error"
    assert pearl_store.count_pearls()["total"] == 0
    assert llm_budget_tokens() == before


def llm_budget_tokens():
    import llm_budget
    return llm_budget.get_usage("write")["tokens"]


def test_moments_must_stay_at_least_the_restored_floor(monkeypatch):
    monkeypatch.delenv(pearls_warm.ENV_FLOOR, raising=False)
    assert pearls_warm.required_moments(1142) == 1142
    assert pearls_warm.required_moments(1152) == 1152
    assert pearls_warm.required_moments(3) == 1142
    _save_route(1)
    with pytest.raises(pearls_warm.Failed) as failed:
        pearls_warm.run(fill=lambda _pearl: _bag())
    assert "1142" in str(failed.value)
    assert pearl_store.count_moments(OFFICIAL_VOYAGE_ID) == 0
    assert not (pearls_warm._job_dir(mkdir=False) / ".done").is_file()
    status = pearls_warm.public_status()
    assert status["found"] == status["routePoints"]
    assert status["state"] == "error"
    blob = json.dumps(status)
    assert "/" not in blob


def test_status_block_has_no_private_path():
    _save_route(1)
    pearls_warm.run(fill=lambda _pearl: _bag())
    from main import app
    body = TestClient(app).get("/ici/warm/status").json()
    warm = body["pearlsWarm"]
    assert warm["state"] == "done"
    assert warm["found"] == warm["routePoints"]
    assert warm["done"] >= 1
    blob = json.dumps(warm)
    assert "/" not in blob
    assert "path" not in warm
    assert ici_warm.warm_enabled() is False


def test_cli_estimate_does_not_keep_llm_mode(monkeypatch):
    _save_route(2)
    monkeypatch.delenv("NAVIGUIDE_LLM_MODE", raising=False)
    assert pearls_warm.main(["--estimate"]) == 0
    assert os.environ.get("NAVIGUIDE_LLM_MODE") is None
    assert pearl_store.count_pearls()["total"] == 0
