"""Each served page names its own canonical and language alternates, and no shared
link answers 404 (the redirects themselves are Codex's, tested in test_spa_redirects.py)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.main as main
from app.spa_client_routes import normalize_client_path, page_head, page_lang

# The real page head, so the rewrite is checked against what the site serves.
_REAL_INDEX = (Path(__file__).resolve().parents[2] / "frontend" / "index.html").read_text(encoding="utf-8")
_SITE = "https://escales.naviguide.fr"

# Links that may already be shared (Devpost, the video, old builds): none may answer 404.
SHARED_LINKS = [
    "/",
    "/?lang=fr",
    "/?paypal=return",
    "/en",
    "/fr",
    "/en/",
    "/fr/escales/wishlists",
    "/en/projects/projet-recifs/onboarding",
    "/fr/does-not-exist",
    "/FR",
    "/escales",
    "/escales/wishlists",
    "/escales/wishlists?lang=fr",
    "/projects/projet-recifs/onboarding",
    "/unknown-spa-route",
    "/wp-login.php",
]


@pytest.fixture()
def client(monkeypatch, tmp_path) -> TestClient:
    dist = tmp_path / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text(_REAL_INDEX, encoding="utf-8")
    (dist / "robots.txt").write_text("User-agent: *\n", encoding="utf-8")
    monkeypatch.setattr(main, "frontend_dist", lambda: dist)
    application = FastAPI()
    main.attach_frontend(application)
    return TestClient(application)


@pytest.mark.parametrize("path", SHARED_LINKS)
def test_no_shared_link_answers_404(client, path):
    first = client.get(path, follow_redirects=False)
    assert first.status_code in (200, 301, 302, 307, 308), first.status_code
    landed = client.get(path)
    assert landed.status_code == 200
    assert '<div id="root">' in landed.text
    assert client.head(path).status_code == 200


def test_old_language_links_land_on_the_page_in_that_language(client):
    for path, lang in (("/fr", "fr"), ("/en", "en"), ("/fr/escales/wishlists", "fr")):
        landed = client.get(path)
        assert f'<html lang="{lang}">' in landed.text, path


def test_a_real_file_is_still_served_as_itself(client):
    res = client.get("/robots.txt")
    assert res.status_code == 200
    assert "<div" not in res.text


def test_api_paths_never_get_the_page(client):
    res = client.get("/api/not-a-route")
    assert res.status_code == 404
    assert "<div" not in res.text


def _links(text: str) -> dict[str, str]:
    found = {"canonical": re.search(r'<link rel="canonical" href="([^"]+)"', text).group(1)}
    for code, href in re.findall(r'<link rel="alternate" hreflang="([^"]+)" href="([^"]+)"', text):
        found[code] = href
    found["og:url"] = re.search(r'<meta property="og:url" content="([^"]+)"', text).group(1)
    found["lang"] = re.search(r'<html lang="([^"]+)">', text).group(1)
    return found


def test_each_language_of_the_map_is_its_own_canonical(client):
    en = _links(client.get("/").text)
    fr = _links(client.get("/?lang=fr").text)
    assert en == {
        "canonical": f"{_SITE}/",
        "en": f"{_SITE}/",
        "fr": f"{_SITE}/?lang=fr",
        "x-default": f"{_SITE}/",
        "og:url": f"{_SITE}/",
        "lang": "en",
    }
    assert fr["canonical"] == f"{_SITE}/?lang=fr" == fr["fr"] == fr["og:url"]
    assert fr["en"] == f"{_SITE}/" and fr["lang"] == "fr"
    assert 'property="og:locale" content="fr_FR"' in client.get("/?lang=fr").text
    # ?lang=en is the English page: it names "/" as its canonical, as hreflang does.
    assert _links(client.get("/?lang=en").text)["canonical"] == f"{_SITE}/"


def test_the_wishlist_page_does_not_declare_the_map_as_its_canonical(client):
    links = _links(client.get("/escales/wishlists?lang=fr").text)
    assert links["canonical"] == f"{_SITE}/escales/wishlists?lang=fr"
    assert links["en"] == f"{_SITE}/escales/wishlists"
    assert links["x-default"] == f"{_SITE}/escales/wishlists"


def test_every_alternate_appears_once():
    out = page_head(_REAL_INDEX, "", "lang=fr")
    assert out.count('rel="canonical"') == 1
    assert out.count('hreflang="en"') == out.count('hreflang="fr"') == out.count('hreflang="x-default"') == 1
    # The rest of the head is untouched.
    assert out.count("og:image") == _REAL_INDEX.count("og:image")


def test_a_head_without_canonical_is_left_alone():
    plain = "<!doctype html><title>BI Escales</title>"
    assert page_head(plain, "", "lang=fr") == plain


def test_helpers():
    assert normalize_client_path("/") == ""
    assert normalize_client_path("/escales/wishlists/") == "escales/wishlists"
    assert page_lang("lang=FR") == "fr"
    assert page_lang("lang=de") == "en"
    assert page_lang("") == "en"
