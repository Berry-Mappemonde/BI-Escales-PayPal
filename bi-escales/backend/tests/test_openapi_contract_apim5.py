"""OpenAPI path/method contract at ed21eec, plus APIM-5 documentation checks.

The spec is built in a fresh interpreter with ESCALES_ENABLED=1. Importing
``app.main`` in this process would register the escales routers for every
other test, because the flag is read at import time.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
_SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "openapi_paths_ed21eec.json"
_COMMIT = "ed21eec98c71b34371f8efe38225955838ae70f0"
_TEST2 = "https://bi-escales-api-test2.onrender.com"

# Explicit ids only. Every other operationId must stay the ed21eec value.
_SHORT_OPERATION_IDS = {
    "POST /api/escales/demo/stops/{milestone_id}/simulate-arrival": "demo_simulate_arrival",
    "POST /api/escales/demo/stops/{milestone_id}/cancel": "demo_cancel_stop",
    "POST /api/escales/demo/stops/{milestone_id}/reset": "demo_reset_stop",
    "GET /api/escales/channel3/catalog": "get_channel3_catalog",
    "GET /api/escales/channel3/catalog/{channel3_product_id}": "get_channel3_catalog_item",
    "GET /api/escales/channel3/catalog/by-project/{project_id}/fund": "get_channel3_item_fund",
    "GET /api/escales/wishlists/{wishlist_id}": "get_public_wishlist",
    "GET /api/escales/treasurer/wishlists": "treasurer_list_wishlists",
    "POST /api/escales/treasurer/wishlists": "treasurer_create_wishlist",
    "POST /api/escales/treasurer/wishlists/{wishlist_id}/items": "treasurer_add_wishlist_item",
    "DELETE /api/escales/treasurer/wishlists/{wishlist_id}/items/{channel3_product_id}": (
        "treasurer_remove_wishlist_item"
    ),
    "POST /api/escales/treasurer/wishlists/{wishlist_id}/publish": "treasurer_publish_wishlist",
}


def _load_spec() -> dict:
    env = os.environ.copy()
    env["ESCALES_ENABLED"] = "1"
    code = "import json, sys\nfrom app.main import app\njson.dump(app.openapi(), sys.stdout)\n"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-4000:])
    return json.loads(proc.stdout)


def _operations(spec: dict) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            if method.startswith("x-") or not isinstance(operation, dict):
                continue
            found[f"{method.upper()} {path}"] = operation
    return found


@pytest.fixture(scope="module")
def spec() -> dict:
    return _load_spec()


@pytest.fixture(scope="module")
def snapshot() -> dict:
    return json.loads(_SNAPSHOT.read_text(encoding="utf-8"))


def test_openapi_path_method_snapshot(spec, snapshot):
    assert snapshot["commit"] == _COMMIT
    pairs = {(path, method) for path, method in snapshot["pairs"]}
    live = set()
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            if isinstance(operation, dict) and not method.startswith("x-"):
                live.add((path, method))
    assert live == pairs


def test_openapi_status_codes_unchanged(spec, snapshot):
    live = {
        key: sorted(operation["responses"])
        for key, operation in _operations(spec).items()
    }
    expected = {key: list(codes) for key, codes in snapshot["status_codes"].items()}
    assert live == expected


def test_openapi_operation_ids(spec, snapshot):
    live = {key: operation["operationId"] for key, operation in _operations(spec).items()}
    assert set(live) == set(snapshot["operation_ids"])
    for key, operation_id in live.items():
        if key in _SHORT_OPERATION_IDS:
            assert operation_id == _SHORT_OPERATION_IDS[key]
            assert len(operation_id) <= 50
            assert len(snapshot["operation_ids"][key]) > 50
        else:
            assert operation_id == snapshot["operation_ids"][key]
    blocking = (
        "DELETE /api/escales/treasurer/wishlists/{wishlist_id}/items/{channel3_product_id}"
    )
    assert len(snapshot["operation_ids"][blocking]) > 100
    assert live[blocking] == "treasurer_remove_wishlist_item"


def test_openapi_operations_are_documented(spec):
    for key, operation in _operations(spec).items():
        assert (operation.get("summary") or "").strip(), key
        assert (operation.get("description") or "").strip(), key
    documented_prefixes = (
        "/api/escales/demo/",
        "/api/escales/channel3/",
        "/api/escales/wishlists",
        "/api/escales/treasurer/wishlists",
        "/api/escales/",
        "/api/health",
    )
    covered = [
        key
        for key in _operations(spec)
        if any(key.split(" ", 1)[1].startswith(prefix) or key.endswith(prefix) for prefix in documented_prefixes)
    ]
    assert covered


def test_openapi_info_contact_servers_and_tags(spec):
    info = spec["info"]
    assert "sandbox" in info["description"].lower()
    assert "12 Nov 2026" in info["description"]
    assert info["contact"]["name"] == "Association Berry-Mappemonde"
    assert info["contact"]["url"] == "https://devpost.com/software/bi-escales-pay-only-if-we-sail"
    assert "email" not in info["contact"]
    assert spec["servers"][0]["url"] == _TEST2
    names = [tag["name"] for tag in spec["tags"]]
    for name in ("health", "escales", "escales-webhooks", "escales-demo", "channel3-wishlists"):
        assert name in names
        assert spec["tags"][names.index(name)]["description"].strip()
    health = spec["paths"]["/api/health"]["get"]
    assert health["tags"] == ["health"]
    assert health["operationId"] == "health_api_health_get"
