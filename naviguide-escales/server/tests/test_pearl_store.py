"""Base embarquée (SQLite) des perles."""
import json
import time

import ici_engine
import pearl_store
from ici_engine import reset_caches, thin_cache_get, thin_cache_key, thin_cache_put


def test_put_get_count_and_rich_never_downgraded():
    key = thin_cache_key(46.15, -1.16, 30)
    assert pearl_store.get_pearl(key) is None
    assert pearl_store.put_pearl(key, {"zee": {"mrgid": 5677}}, "thin", 46.15, -1.16) is True
    row = pearl_store.get_pearl(key)
    assert row["kind"] == "thin" and row["bag"]["zee"]["mrgid"] == 5677
    assert pearl_store.put_pearl(key, {"zee": {"mrgid": 5677}, "science": []}, "rich") is True
    assert pearl_store.get_pearl(key)["kind"] == "rich"
    # A thin write never replaces a rich pearl.
    assert pearl_store.put_pearl(key, {"zee": None}, "thin") is False
    assert pearl_store.get_pearl(key)["kind"] == "rich"
    assert pearl_store.count_pearls() == {"total": 1, "rich": 1, "thin": 0}
    info = pearl_store.info()
    assert info["path"].endswith("naviguide.sqlite") and info["bytes"] > 0


def test_kv_put_rejects_a_payload_bigger_than_two_megabytes():
    huge = {"features": ["x" * 3_000_000]}
    assert pearl_store.kv_put("amp-bbox", "cell-0", huge) is False
    assert pearl_store.kv_get("amp-bbox", "cell-0") is None
    assert pearl_store.kv_put("amp-bbox", "cell-0", {"features": [{"id": 1}]}) is True
    assert pearl_store.kv_get("amp-bbox", "cell-0")["value"]["features"][0]["id"] == 1


def test_purge_by_age():
    old = time.time() - 40 * 86400
    pearl_store.put_pearl("a", {"x": 1}, "rich", ts=old)
    pearl_store.put_pearl("b", {"x": 2}, "rich")
    assert pearl_store.purge_pearls(30 * 86400) == 1
    assert pearl_store.get_pearl("a") is None and pearl_store.get_pearl("b") is not None


def test_engine_cache_is_write_through_and_survives_a_memory_reset():
    reset_caches()
    key = thin_cache_key(43.0, 5.0, 30)
    thin_cache_put(key, {"zee": {"mrgid": 5677}, "sources": {"bi": "ok"}}, "thin", 43.0, 5.0)
    assert thin_cache_get(key)["zee"]["mrgid"] == 5677
    reset_caches()  # memory gone, SQLite still there
    assert thin_cache_get(key)["zee"]["mrgid"] == 5677
    # A thin pearl does not satisfy a rich request; a rich one satisfies both.
    assert thin_cache_get(key, rich=True) is None
    thin_cache_put(key, {"zee": {"mrgid": 5677}, "science": [{"name": "s"}]}, "rich", 43.0, 5.0)
    assert thin_cache_get(key, rich=True)["science"][0]["name"] == "s"
    assert thin_cache_get(key)["science"][0]["name"] == "s"
    # ... and is never downgraded, in memory or on disk.
    thin_cache_put(key, {"zee": None}, "thin")
    assert thin_cache_get(key, rich=True) is not None
    reset_caches()
    assert thin_cache_get(key, rich=True) is not None


def test_stale_pearls_are_misses(monkeypatch):
    reset_caches()
    key = thin_cache_key(10.0, 10.0, 30)
    pearl_store.put_pearl(key, {"x": 1}, "thin", ts=time.time() - 8 * 86400)
    assert thin_cache_get(key) is None, "thin: 7 days"
    pearl_store.put_pearl(key, {"x": 1}, "rich", ts=time.time() - 8 * 86400)
    assert thin_cache_get(key) is not None, "rich: 30 days"
    pearl_store.put_pearl(key, {"x": 1}, "rich", ts=time.time() - 31 * 86400)
    reset_caches()
    assert thin_cache_get(key) is None


def test_legacy_json_is_migrated_once(tmp_path):
    import ici_warm
    path = ici_warm.cache_path()
    path.write_text(json.dumps({
        thin_cache_key(46.15, -1.16, 30): {"ts": time.time(), "bag": {"zee": {"mrgid": 5677}}},
        "stale": {"ts": 0, "bag": {}},
        "bad": 1,
    }))
    assert ici_warm.load_cache_from_disk() == 1
    assert not path.exists() and path.with_suffix(".json.migrated").exists()
    reset_caches()
    assert thin_cache_get(thin_cache_key(46.15, -1.16, 30))["zee"]["mrgid"] == 5677
    assert ici_warm.load_cache_from_disk() == 0  # nothing left to migrate
    assert ici_warm.status()["store"]["total"] == 1
