"""Postman partner collection — static sandbox walkthrough (not loaded by the app)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COLLECTION = ROOT / "postman" / "escales.postman_collection.json"
ENVIRONMENT = ROOT / "postman" / "escales.sandbox.postman_environment.json"


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
    base_url = next(v for v in data["variable"] if v["key"] == "baseUrl")
    assert base_url["value"] == "http://127.0.0.1:8000"
    text = COLLECTION.read_text(encoding="utf-8")
    assert "{{SANDBOX_ADMIN_KEY}}" in text
    assert "bi-escales-api.onrender.com" not in text
    assert "PAYPAL_CLIENT_SECRET" not in text


def test_postman_render_environment_file():
    assert ENVIRONMENT.is_file()
    env = json.loads(ENVIRONMENT.read_text(encoding="utf-8"))
    base = next(v for v in env["values"] if v["key"] == "baseUrl")
    assert base["value"] == "https://bi-escales-api.onrender.com"
