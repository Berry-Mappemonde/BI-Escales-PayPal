"""Postman partner collection and sandbox environment ship in-repo (not loaded by the app)."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COLLECTION = ROOT / "postman" / "escales.postman_collection.json"
ENVIRONMENT = ROOT / "postman" / "escales.sandbox.postman_environment.json"
PROD_HOST = "bi-escales-api.onrender.com"


def test_collection_covers_create_authorize_capture_void():
    data = json.loads(COLLECTION.read_text(encoding="utf-8"))
    names = " ".join(item["name"] for item in data["item"]).lower()
    for step in ("create pledge", "authorize", "capture", "void"):
        assert step in names
    text = COLLECTION.read_text(encoding="utf-8")
    assert PROD_HOST not in text
    assert "PAYPAL_CLIENT_SECRET" not in text


def test_environment_targets_test2_sandbox_without_secrets():
    env = json.loads(ENVIRONMENT.read_text(encoding="utf-8"))
    values = {v["key"]: v for v in env["values"]}
    assert values["baseUrl"]["value"] == "https://bi-escales-api-test2.onrender.com"
    assert values["adminKey"]["value"] == ""
    assert values["adminKey"]["type"] == "secret"
    used = set(re.findall(r"\{\{(\w+)\}\}", COLLECTION.read_text(encoding="utf-8")))
    assert {"baseUrl", "adminKey", "milestoneId"} <= used
    assert PROD_HOST not in ENVIRONMENT.read_text(encoding="utf-8")
