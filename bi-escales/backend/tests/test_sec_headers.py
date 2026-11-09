"""SEC-HEADERS: security response headers on SPA, API, and error responses."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.main as main
from app.middleware.security_headers import (
    HSTS_VALUE,
    REFERRER_POLICY,
    X_CONTENT_TYPE_OPTIONS,
    build_csp_enforced,
    build_csp_report_only,
    install_security_headers,
)


def _expected_headers() -> dict[str, str]:
    return {
        "strict-transport-security": HSTS_VALUE,
        "x-content-type-options": X_CONTENT_TYPE_OPTIONS,
        "referrer-policy": REFERRER_POLICY,
        "content-security-policy": build_csp_enforced(),
        "content-security-policy-report-only": build_csp_report_only(),
    }


def _assert_security_headers(response) -> None:
    expected = _expected_headers()
    for name, value in expected.items():
        assert response.headers.get(name) == value, f"{name}: got {response.headers.get(name)!r}"
    assert "preload" not in (response.headers.get("strict-transport-security") or "").lower()
    assert response.headers.get("content-security-policy") == "frame-ancestors 'none'"


def test_security_headers_api_health():
    client = TestClient(main.app)
    res = client.get("/api/health")
    assert res.status_code == 200
    _assert_security_headers(res)


def test_security_headers_spa_root(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>BI Escales</title>", encoding="utf-8")
    monkeypatch.setattr(main, "frontend_dist", lambda: dist)

    application = FastAPI()
    install_security_headers(application)
    main.attach_frontend(application)
    client = TestClient(application)

    res = client.get("/")
    assert res.status_code == 200
    _assert_security_headers(res)


def test_security_headers_on_404():
    client = TestClient(main.app)
    res = client.get("/api/does-not-exist-sec-headers")
    assert res.status_code == 404
    _assert_security_headers(res)


def test_security_headers_disabled(monkeypatch):
    monkeypatch.setenv("ESCALES_SECURITY_HEADERS", "0")
    client = TestClient(main.app)
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.headers.get("strict-transport-security") is None
    assert res.headers.get("content-security-policy") is None
