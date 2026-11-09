"""SITE-META: robots.txt and sitemap.xml served from dist before SPA fallback."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.main as main


def test_robots_and_sitemap_from_dist(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>BI Escales</title>", encoding="utf-8")
    (dist / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n\nSitemap: https://escales.naviguide.fr/sitemap.xml\n",
        encoding="utf-8",
    )
    (dist / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><urlset><url><loc>https://escales.naviguide.fr/</loc></url></urlset>',
        encoding="utf-8",
    )

    monkeypatch.setattr(main, "frontend_dist", lambda: dist)
    application = FastAPI()
    main.attach_frontend(application)
    client = TestClient(application)

    (dist / "favicon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"></svg>',
        encoding="utf-8",
    )

    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    assert client.head("/robots.txt").status_code == 200
    assert robots.headers["content-type"].startswith("text/plain")
    assert "Sitemap:" in robots.text
    assert "<!doctype" not in robots.text.lower()
    assert "<html" not in robots.text.lower()

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    assert client.head("/sitemap.xml").status_code == 200
    assert "xml" in sitemap.headers["content-type"]
    assert "escales.naviguide.fr" in sitemap.text
    assert "<!doctype" not in sitemap.text.lower()
    assert "<html" not in sitemap.text.lower()

    favicon = client.get("/favicon.svg")
    assert favicon.status_code == 200
    assert client.head("/favicon.svg").status_code == 200

    spa = client.get("/unknown-spa-route")
    assert spa.status_code == 404
    assert spa.headers["content-type"].startswith("text/html")
    assert "BI Escales" in spa.text
