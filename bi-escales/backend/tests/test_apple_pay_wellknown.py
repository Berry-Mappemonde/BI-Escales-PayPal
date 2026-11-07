"""Apple Pay sandbox domain association at /.well-known/ (P1-05/P1-06)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

EXPECTED_SIZE = 9094
EXPECTED_PREFIX = b"7B227073704964223A"


def test_apple_pay_domain_association_is_public_text_plain():
    with TestClient(app) as client:
        res = client.get("/.well-known/apple-developer-merchantid-domain-association")
    assert res.status_code == 200
    assert res.headers.get("content-type", "").startswith("text/plain")
    body = res.content
    assert len(body) == EXPECTED_SIZE
    assert body.startswith(EXPECTED_PREFIX)
