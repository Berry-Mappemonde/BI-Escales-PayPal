"""SEO-HEAD-EN: soft 404 for unknown SPA paths; EN-default share meta and lang."""
from __future__ import annotations

import pytest
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

FORBIDDEN_HEAD = (
    "Pay Only If We Sail",
    "si nous partons",
    "Payez seulement si nous partons",
)


def _dist_with_index(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text(_DEFAULT_INDEX, encoding="utf-8")
    return dist


_DEFAULT_INDEX = """<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="description" content="desc en" />
  <title>BI Escales — Pay only when we arrive</title>
  <link rel="canonical" href="https://escales.naviguide.fr/" />
  <link rel="alternate" hreflang="en" href="https://escales.naviguide.fr/en" />
  <link rel="alternate" hreflang="fr" href="https://escales.naviguide.fr/fr" />
  <link rel="alternate" hreflang="x-default" href="https://escales.naviguide.fr/" />
  <meta property="og:title" content="BI Escales — Pay only when we arrive" />
  <meta property="og:description" content="desc en" />
  <meta property="og:url" content="https://escales.naviguide.fr/" />
  <meta property="og:locale" content="en_US" />
  <meta property="og:locale:alternate" content="fr_FR" />
  <meta name="twitter:title" content="BI Escales — Pay only when we arrive" />
  <meta name="twitter:description" content="desc en" />
</head>
<body><div id="root"></div></body>
</html>
"""


def _client(monkeypatch, tmp_path) -> TestClient:
    dist = _dist_with_index(tmp_path)
    monkeypatch.setattr(main, "frontend_dist", lambda: dist)
    application = FastAPI()
    install_security_headers(application)
    main.attach_frontend(application)
    return TestClient(application)


def _assert_security_headers(response) -> None:
    assert response.headers.get("strict-transport-security") == HSTS_VALUE
    assert response.headers.get("x-content-type-options") == X_CONTENT_TYPE_OPTIONS
    assert response.headers.get("referrer-policy") == REFERRER_POLICY
    assert response.headers.get("content-security-policy") == build_csp_enforced()
    assert response.headers.get("content-security-policy-report-only") == build_csp_report_only()


def _assert_no_forbidden_head(html: str) -> None:
    for needle in FORBIDDEN_HEAD:
        assert needle not in html


def test_known_spa_paths_return_200(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    for path in ("/", "/en", "/fr", "/escales/wishlists"):
        res = client.get(path)
        assert res.status_code == 200, path
        assert "<div id=\"root\">" in res.text
        _assert_security_headers(res)


def test_unknown_spa_path_returns_404_with_shell(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    res = client.get("/not-a-real-page-seo-head-en")
    assert res.status_code == 404
    assert res.headers["content-type"].startswith("text/html")
    assert "<div id=\"root\">" in res.text
    _assert_security_headers(res)
    _assert_no_forbidden_head(res.text)


@pytest.mark.parametrize(
    "path,lang,title_snippet,og_locale",
    [
        ("/", "en", "Pay only when we arrive", "en_US"),
        ("/en", "en", "Pay only when we arrive", "en_US"),
        (
            "/fr",
            "fr",
            "Payez seulement à notre arrivée",
            "fr_FR",
        ),
    ],
)
def test_share_meta_and_lang(path, lang, title_snippet, og_locale, monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    res = client.get(path)
    assert res.status_code == 200
    text = res.text
    assert f'<html lang="{lang}"' in text
    assert title_snippet in text
    assert f'property="og:locale" content="{og_locale}"' in text
    assert 'property="og:locale:alternate"' in text
    assert 'hreflang="en"' in text and 'hreflang="fr"' in text
    assert 'hreflang="x-default"' in text
    _assert_no_forbidden_head(text)


def test_unknown_path_keeps_en_default_meta(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    res = client.get("/does-not-exist-seo-meta")
    assert res.status_code == 404
    assert '<html lang="en"' in res.text
    assert "Pay only when we arrive" in res.text
    _assert_no_forbidden_head(res.text)
