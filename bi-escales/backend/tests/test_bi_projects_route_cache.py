"""The projects file is about 3 MB: encode it once, and let the browser reuse its copy."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.bi_projects_catalog as catalog
import app.main as main
from app.bi_projects_catalog import BROWSER_MAX_AGE, projects_geojson_body, reset_bi_projects_cache


def _collection(title: str = "Reef survey") -> dict:
    return {
        "type": "FeatureCollection",
        "name": "BI projects snapshot",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.5, 2.5]},
             "properties": {"id": "p-1", "title": title, "description": "Récifs — été", "funder": "F"}},
        ],
    }


@pytest.fixture
def served(monkeypatch):
    reset_bi_projects_cache()
    state = {"payload": _collection()}

    async def fake():
        return state["payload"]

    monkeypatch.setattr(main, "get_bi_projects_geojson", fake)
    yield TestClient(main.app), state
    reset_bi_projects_cache()


def test_the_body_is_byte_for_byte_what_it_was(served):
    client, state = served
    response = client.get("/bi-projects.geojson")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/geo+json"
    assert response.content == JSONResponse(content=state["payload"]).body
    assert response.json() == state["payload"]


def test_it_carries_an_etag_and_a_short_max_age(served):
    client, _state = served
    response = client.get("/bi-projects.geojson")
    assert response.headers["cache-control"] == f"public, max-age={BROWSER_MAX_AGE}"
    assert BROWSER_MAX_AGE == 300
    etag = response.headers["etag"]
    assert etag.startswith('"') and etag.endswith('"') and len(etag) == 34


def test_a_browser_that_has_the_file_gets_304_and_no_body(served):
    client, _state = served
    etag = client.get("/bi-projects.geojson").headers["etag"]
    again = client.get("/bi-projects.geojson", headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == etag
    # A weak validator, as a proxy may send it, and a list of validators.
    assert client.get("/bi-projects.geojson", headers={"If-None-Match": f"W/{etag}"}).status_code == 304
    assert client.get("/bi-projects.geojson", headers={"If-None-Match": f'"other", {etag}'}).status_code == 304


def test_a_stale_or_foreign_validator_gets_the_file(served):
    client, _state = served
    response = client.get("/bi-projects.geojson", headers={"If-None-Match": '"not-this-one"'})
    assert response.status_code == 200
    assert response.json()["features"][0]["properties"]["id"] == "p-1"


def test_a_refreshed_catalogue_changes_the_etag_and_the_body(served):
    client, state = served
    first = client.get("/bi-projects.geojson")
    state["payload"] = _collection("Mangrove nursery")
    second = client.get("/bi-projects.geojson", headers={"If-None-Match": first.headers["etag"]})
    assert second.status_code == 200
    assert second.headers["etag"] != first.headers["etag"]
    assert second.json()["features"][0]["properties"]["title"] == "Mangrove nursery"


def test_the_payload_is_encoded_once_while_it_is_the_same_object(monkeypatch):
    reset_bi_projects_cache()
    payload = _collection()
    calls = {"n": 0}
    real = json.dumps

    def counted(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(catalog.json, "dumps", counted)
    first = projects_geojson_body(payload)
    for _ in range(5):
        assert projects_geojson_body(payload) == first
    assert calls["n"] == 1
    # Another payload object, even with the same content, is encoded again: identity is the key.
    projects_geojson_body(_collection())
    assert calls["n"] == 2
    reset_bi_projects_cache()


def test_resetting_the_catalogue_cache_forgets_the_encoded_body():
    payload = _collection()
    projects_geojson_body(payload)
    assert catalog._encoded["payload"] is payload
    reset_bi_projects_cache()
    assert catalog._encoded["payload"] is None and catalog._encoded["body"] == b""


def test_non_ascii_text_is_kept_as_text():
    body, _etag = projects_geojson_body(_collection())
    assert "Récifs — été".encode("utf-8") in body
    reset_bi_projects_cache()
