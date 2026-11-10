"""EN-default share meta in the first HTML shell served for `/` (no server-side path rewriting)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.main as main

FORBIDDEN_HEAD = (
    "Pay Only If We Sail",
    "si nous partons",
    "Payez seulement si nous partons",
)

_DEFAULT_INDEX = """<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="description" content="desc en" />
  <title>BI Escales — Pay only when we arrive</title>
  <link rel="canonical" href="https://escales.naviguide.fr/" />
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
    dist = tmp_path / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text(_DEFAULT_INDEX, encoding="utf-8")
    monkeypatch.setattr(main, "frontend_dist", lambda: dist)
    application = FastAPI()
    main.attach_frontend(application)
    return TestClient(application)


def test_root_serves_en_default_share_meta(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    res = client.get("/")
    assert res.status_code == 200
    text = res.text
    assert '<html lang="en"' in text
    assert "Pay only when we arrive" in text
    assert 'property="og:locale" content="en_US"' in text
    assert 'property="og:locale:alternate" content="fr_FR"' in text
    for needle in FORBIDDEN_HEAD:
        assert needle not in text
