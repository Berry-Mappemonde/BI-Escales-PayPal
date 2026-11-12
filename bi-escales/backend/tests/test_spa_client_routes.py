"""No address answers 404 with the page: known paths get the page (with their own
canonical and language alternates), old /en and /fr links and unknown paths move."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.main as main
from app.spa_client_routes import (
    client_redirect,
    is_known_client_route,
    normalize_client_path,
    page_head,
    page_lang,
)

# The real page head, so the rewrite is checked against what the site serves.
_REAL_INDEX = (Path(__file__).resolve().parents[2] / "frontend" / "index.html").read_text(encoding="utf-8")
_SITE = "https://escales.naviguide.fr"

KNOWN = [
    "/",
    "/escales/wishlists",
    "/escales/wishlists/",
    "/projects/projet-recifs/onboarding",
    "/projects/projet-recifs/onboarding/return",
    "/projects/a%20b/onboarding/return",
]

# (path, where it moves, status)
OLD_LANGUAGE_LINKS = [
    ("/en", "/?lang=en", 301),
    ("/fr", "/?lang=fr", 301),
    ("/en/", "/?lang=en", 301),
    ("/FR", "/?lang=fr", 301),
    ("/fr/escales/wishlists", "/escales/wishlists?lang=fr", 301),
    ("/en/projects/projet-recifs/onboarding/return", "/projects/projet-recifs/onboarding/return?lang=en", 301),
    ("/fr/does-not-exist", "/?lang=fr", 301),
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
    "/english",
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


@pytest.mark.parametrize("path", KNOWN)
def test_known_paths_answer_200_with_the_page(client, path):
    res = client.get(path, follow_redirects=False)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert '<div id="root">' in res.text
    assert client.head(path, follow_redirects=False).status_code == 200


@pytest.mark.parametrize(("path", "location", "status"), OLD_LANGUAGE_LINKS)
def test_old_language_links_move_to_the_same_page_in_that_language(client, path, location, status):
    res = client.get(path, follow_redirects=False)
    assert res.status_code == status
    assert res.headers["location"] == location
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", UNKNOWN)
def test_unknown_paths_move_to_the_map_and_never_answer_404(client, path):
    res = client.get(path, follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == "/"
    landed = client.get(path)
    assert landed.status_code == 200
    assert '<div id="root">' in landed.text
    assert client.head(path).status_code == 200


def test_the_query_string_survives_the_move(client):
    res = client.get("/fr?paypal=return&lang=en", follow_redirects=False)
    assert res.headers["location"] == "/?lang=fr&paypal=return"
    res = client.get("/old-page?ref=devpost", follow_redirects=False)
    assert res.headers["location"] == "/?ref=devpost"


def test_paypal_return_addresses_stay_200(client):
    # Orders, vault and subscriptions come back to "/" with a query string.
    for query in ("?paypal=return", "?vault=approved", "?sub=approved", "?lang=fr"):
        assert client.get("/" + query, follow_redirects=False).status_code == 200


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
    assert is_known_client_route("") is True
    assert client_redirect("/", "") is None
    assert client_redirect("/escales/wishlists", "lang=fr") is None
    assert page_lang("lang=FR") == "fr"
    assert page_lang("lang=de") == "en"
    assert page_lang("") == "en"


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
