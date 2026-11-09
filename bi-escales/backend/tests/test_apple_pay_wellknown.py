"""Apple Pay sandbox domain association at /.well-known/ (P1-05/P1-06)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

EXPECTED_SIZE = 9094
EXPECTED_PREFIX = b"7B227073704964223A"
BUNDLED_ASSOCIATION = (
    Path(__file__).resolve().parents[1]
    / "static"
    / ".well-known"
    / "apple-developer-merchantid-domain-association"
)


def test_apple_pay_domain_association_is_public_octet_stream():
    expected_sha256 = hashlib.sha256(BUNDLED_ASSOCIATION.read_bytes()).hexdigest()
    with TestClient(app) as client:
        res = client.get(
            "/.well-known/apple-developer-merchantid-domain-association",
            follow_redirects=False,
        )
    assert res.status_code == 200
    assert res.headers.get("location") is None
    assert res.headers.get("content-type", "").startswith("application/octet-stream")
    body = res.content
    assert len(body) == EXPECTED_SIZE
    assert body.startswith(EXPECTED_PREFIX)
    assert hashlib.sha256(body).hexdigest() == expected_sha256
