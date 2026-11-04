"""29 sept. : les grosses réponses JSON (l'horloge officielle : 3,9 Mo → 335 ko) partent gzippées quand le
client l'accepte — sans quoi le tunnel du poste de recette mettait plus d'une minute par horloge et le poste distant
voyait le bateau au jour 0. Les petites réponses restent en clair."""
from fastapi.testclient import TestClient

import main


def test_large_json_is_gzipped_when_accepted():
    client = TestClient(main.app)
    r = client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"
    assert r.json().get("openapi")   # httpx décode : le corps lu est bien du JSON


def test_plain_when_client_does_not_accept_gzip():
    client = TestClient(main.app)
    r = client.get("/openapi.json", headers={"Accept-Encoding": "identity"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") is None


def test_small_response_stays_plain():
    client = TestClient(main.app)
    r = client.get("/", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert len(r.content) < 2048
    assert r.headers.get("content-encoding") is None
