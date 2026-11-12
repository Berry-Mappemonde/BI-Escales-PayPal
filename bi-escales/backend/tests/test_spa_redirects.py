"""Shared links: /en and /fr redirect to ?lang=, unknown paths to the map."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import attach_frontend


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    (tmp_path / "index.html").write_text("<html>map</html>", encoding="utf-8")
    (tmp_path / "og-image.png").write_bytes(b"png")
    monkeypatch.setattr("app.main.frontend_dist", lambda: tmp_path)
    application = FastAPI()
    attach_frontend(application)
    return TestClient(application)


def test_language_prefixes_and_unknown_paths(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    home = client.get("/en", follow_redirects=False)
    assert home.status_code == 302
    assert home.headers["location"] == "/?lang=en"

    nested = client.get("/fr/stops?from=share", follow_redirects=False)
    assert nested.status_code == 302
    assert nested.headers["location"] == "/stops?from=share&lang=fr"
    unknown_stop = client.get("/stops", params=[("from", "share"), ("lang", "fr")], follow_redirects=False)
    assert unknown_stop.status_code == 302
    assert unknown_stop.headers["location"] == "/?from=share&lang=fr"

    unknown = client.get("/this-should-not-exist", params=[("paypal", "return"), ("paypal", "again")], follow_redirects=False)
    assert unknown.status_code == 302
    assert unknown.headers["location"] == "/?paypal=return&paypal=again"

    assert client.get("/og-image.png").status_code == 200
    assert client.get("/").status_code == 200
    assert "map" in client.get("/").text


def test_known_spa_routes_are_the_app(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    onboarding = client.get("/projects/demo/onboarding", follow_redirects=False)
    assert onboarding.status_code == 200
    assert "map" in onboarding.text

    seller = client.get(
        "/projects/demo/onboarding/return",
        params=[("merchantIdInPayPal", "X"), ("permissionsGranted", "true")],
        follow_redirects=False,
    )
    assert seller.status_code == 200
    assert seller.headers["content-type"].startswith("text/html")

    lists = client.get("/escales/wishlists", follow_redirects=False)
    assert lists.status_code == 200

    french_lists = client.get("/fr/escales/wishlists", follow_redirects=False)
    assert french_lists.status_code == 302
    assert french_lists.headers["location"] == "/escales/wishlists?lang=fr"
    assert client.get("/escales/wishlists", params={"lang": "fr"}).status_code == 200

    french_onboarding = client.get("/fr/projects/demo/onboarding", follow_redirects=False)
    assert french_onboarding.status_code == 302
    assert french_onboarding.headers["location"] == "/projects/demo/onboarding?lang=fr"
    assert client.get("/projects/demo/onboarding", params={"lang": "fr"}).status_code == 200


def test_language_redirects_never_leave_the_site(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    for lang in ("en", "fr"):
        for suffix in ("//evil.example", "/%5Cevil.example", "///evil.example"):
            response = client.get(f"/{lang}{suffix}?paypal=return&paypal=again", follow_redirects=False)
            assert response.status_code == 302
            assert response.headers["location"] == f"/evil.example?paypal=return&paypal=again&lang={lang}"
