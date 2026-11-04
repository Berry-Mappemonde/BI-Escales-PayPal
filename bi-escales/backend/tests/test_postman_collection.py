"""Postman partner collection — static sandbox walkthrough (not loaded by the app)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COLLECTION = ROOT / "postman" / "escales.postman_collection.json"


def test_postman_collection_covers_sandbox_flow():
    assert COLLECTION.is_file(), "postman collection must ship in-repo"
    data = json.loads(COLLECTION.read_text(encoding="utf-8"))
    names = [item["name"] for item in data["item"]]
    assert "Features (partner flags)" in names
    assert any("Create pledge" in name for name in names)
    assert any("Authorize" in name for name in names)
    assert any("Capture" in name for name in names)
    assert any("Void" in name for name in names)
    assert any("webhook" in name.lower() for name in names)
    keys = {var["key"] for var in data["variable"]}
    assert "baseUrl" in keys
    assert "adminKey" in keys
    text = COLLECTION.read_text(encoding="utf-8")
    assert "{{SANDBOX_ADMIN_KEY}}" in text
    assert "PAYPAL_CLIENT_SECRET" not in text
