"""Shared links: /en and /fr redirect to ?lang=, unknown paths to the map."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import attach_frontend


def test_language_prefixes_and_unknown_paths(tmp_path: Path, monkeypatch):
    (tmp_path / "index.html").write_text("<html>map</html>", encoding="utf-8")
    (tmp_path / "og-image.png").write_bytes(b"png")
    monkeypatch.setattr("app.main.frontend_dist", lambda: tmp_path)
    application = FastAPI()
    attach_frontend(application)
    client = TestClient(application)

    home = client.get("/en", follow_redirects=False)
    assert home.status_code == 301
    assert home.headers["location"] == "/?lang=en"

    nested = client.get("/fr/stops?from=share", follow_redirects=False)
    assert nested.status_code == 301
    assert nested.headers["location"] == "/stops?from=share&lang=fr"

    unknown = client.get("/this-should-not-exist", follow_redirects=False)
    assert unknown.status_code == 301
    assert unknown.headers["location"] == "/"

    assert client.get("/og-image.png").status_code == 200
    assert client.get("/").status_code == 200
    assert "map" in client.get("/").text
