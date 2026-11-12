"""An unknown path gets the page with status 404; the paths the app knows get 200."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.main as main
from app.spa_client_routes import is_known_client_route, normalize_client_path

_INDEX = """<!doctype html>
<html lang="en">
<head><title>BI Escales — Pay only when we arrive</title></head>
<body><div id="root"></div></body>
</html>
"""

KNOWN = [
    "/",
    "/escales/wishlists",
    "/escales/wishlists/",
    "/fr/escales/wishlists",
    "/projects/projet-recifs/onboarding",
    "/projects/projet-recifs/onboarding/return",
    "/projects/a%20b/onboarding/return",
]

UNKNOWN = [
    "/unknown-spa-route",
    "/escales",
    "/escales/wishlists/extra",
    "/wishlists",
    "/projects",
    "/projects/projet-recifs",
    "/projects/projet-recifs/onboarding/return/again",
    "/projects//onboarding",
    "/wp-login.php",
]


@pytest.fixture()
def client(monkeypatch, tmp_path) -> TestClient:
    dist = tmp_path / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text(_INDEX, encoding="utf-8")
    (dist / "robots.txt").write_text("User-agent: *\n", encoding="utf-8")
    monkeypatch.setattr(main, "frontend_dist", lambda: dist)
    application = FastAPI()
    main.attach_frontend(application)
    return TestClient(application)


@pytest.mark.parametrize("path", KNOWN)
def test_known_paths_answer_200_with_the_page(client, path):
    res = client.get(path)
    assert res.status_code == 200
    assert '<div id="root">' in res.text


@pytest.mark.parametrize("path", UNKNOWN)
def test_unknown_paths_answer_404_and_still_send_the_page(client, path):
    res = client.get(path)
    assert res.status_code == 404
    assert res.headers["content-type"].startswith("text/html")
    assert '<div id="root">' in res.text
    assert client.head(path).status_code == 404


def test_paypal_return_addresses_stay_200(client):
    # Orders, vault and subscriptions come back to "/" with a query string.
    for query in ("?paypal=return", "?vault=approved", "?sub=approved", "?lang=fr"):
        assert client.get("/" + query).status_code == 200


def test_a_real_file_is_still_served_as_itself(client):
    res = client.get("/robots.txt")
    assert res.status_code == 200
    assert "<div" not in res.text


def test_api_paths_never_get_the_page(client):
    res = client.get("/api/not-a-route")
    assert res.status_code == 404
    assert "<div" not in res.text


def test_normalize_client_path():
    assert normalize_client_path("/") == ""
    assert normalize_client_path("") == ""
    assert normalize_client_path("/escales/wishlists/") == "escales/wishlists"
    assert is_known_client_route("") is True


def test_the_list_follows_the_frontend_router():
    """Root.tsx decides what the app shows; if its paths change, this list must follow."""
    root = Path(__file__).resolve().parents[2] / "frontend" / "src" / "Root.tsx"
    text = root.read_text(encoding="utf-8")
    assert '"/escales/wishlists"' in text
    assert 'path.endsWith("/escales/wishlists")' in text
    assert r"/^\/projects\/([^/]+)\/onboarding$/" in text
    assert r"/^\/projects\/([^/]+)\/onboarding\/return$/" in text
    # Exactly these two kinds of path are matched there: a third needs a line here and in spa_client_routes.py.
    assert text.count("path.match(") == 2
