"""BI stays dark unless BI_API_URL is set. No real network: a transport
that records every request, and constructors that refuse an unmocked one.
"""
import asyncio
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

import bi_proxy
import bi_upstream
import climatology_atlas
import ici_engine
import main
from amp_nogo import load_forbidden_nogo, reset_nogo_cache
from bi_upstream import BiDisabled
from climatology_atlas import atlas_wind_at, fetch_atlas_crossings, fetch_atlas_point, reset_atlas_cache
from ici_engine import _cached_fc, _get_json, fill_dossier, reset_caches

BASE = "http://bi.test/api"


def _looks_like_bi(url: str) -> bool:
    text = str(url)
    return (
        "blueintelligence.online" in text
        or "127.0.0.1:9" in text
        or text.startswith("None")
        or "bi.test" in text
    )


def _boom_handler(seen: list):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url}")
        raise AssertionError(f"unmocked outbound {request.method} {request.url}")

    return handler


def _install_http_guard(monkeypatch, seen: list, handler):
    """Any Client/AsyncClient built without a transport, and any httpx.get, hits `handler`."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    real_async = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs.setdefault("transport", transport)
        return real_client(*args, **kwargs)

    def aclient(*args, **kwargs):
        kwargs.setdefault("transport", transport)
        return real_async(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    monkeypatch.setattr(httpx, "AsyncClient", aclient)

    def get(url, *args, **kwargs):
        seen.append(f"GET {url}")
        raise AssertionError(f"unmocked outbound GET {url}")

    monkeypatch.setattr(httpx, "get", get)
    return transport


@pytest.fixture(autouse=True)
def _reset_bi_state(monkeypatch, tmp_path):
    # Cache disque isolé : sur un poste de dev, ~/.cache/naviguide/bi-cache peut déjà
    # contenir la cellule demandée, et un HIT masquerait le 502 attendu sans BI.
    monkeypatch.setenv("NAVIGUIDE_BI_CACHE_DIR", str(tmp_path / "bi-cache"))
    bi_upstream._disabled_logged = False
    reset_atlas_cache()
    reset_nogo_cache()
    reset_caches()
    bi_proxy.reset()
    main._catalog_cache.clear()
    main._catalog_tasks.clear()
    yield
    reset_atlas_cache()
    reset_nogo_cache()
    reset_caches()
    bi_proxy.reset()
    main._catalog_cache.clear()
    main._catalog_tasks.clear()


def test_disabled_is_logged_once(monkeypatch, caplog):
    monkeypatch.delenv("BI_API_URL", raising=False)
    with caplog.at_level(logging.WARNING, logger="naviguide-simulator.bi"):
        for _ in range(4):
            assert bi_upstream.bi_base() is None
            assert ici_engine.bi_base() is None
            assert bi_proxy.bi_base() is None
            assert climatology_atlas.bi_base() is None
        monkeypatch.setenv("BI_API_URL", "   ")
        assert bi_upstream.bi_base() is None
    messages = [rec.getMessage() for rec in caplog.records if rec.name == "naviguide-simulator.bi"]
    assert messages == ["BI disabled: BI_API_URL is not set"]


def test_unset_makes_no_request_and_ici_falls_back(monkeypatch):
    monkeypatch.delenv("BI_API_URL", raising=False)
    monkeypatch.delenv("NAVIGUIDE_CATALOG_UPSTREAM", raising=False)
    monkeypatch.setenv("NAVIGUIDE_ICI_WARM", "0")
    seen: list[str] = []
    _install_http_guard(monkeypatch, seen, _boom_handler(seen))

    async def engine():
        async with httpx.AsyncClient() as client:
            with pytest.raises(BiDisabled):
                await _get_json(client, "https://blueintelligence.online/api/amp/stats")
            with pytest.raises(BiDisabled):
                await ici_engine.fetch_amp_features(client, 46.15, -1.16)

    asyncio.run(engine())

    assert fetch_atlas_crossings(46.15, -1.16, 14.6, -61.0, 6) is None
    assert fetch_atlas_point(46.15, -1.16, 6) is None
    assert atlas_wind_at(10.0, -30.0, 6)["source"] == "zone_fallback"

    reset_nogo_cache()
    assert load_forbidden_nogo() == []

    with TestClient(main.app) as client:
        proxy = client.get("/bi/climatology/point", params={"lat": 46.15, "lon": -1.16, "month": 6})
        assert proxy.status_code == 502
        assert "atlas unavailable" in proxy.json()["detail"]

        catalog = client.get("/proxy/catalog/marinas", params={"bbox": "-5,40,10,55"})
        assert catalog.status_code == 502
        assert "indisponible" in catalog.json()["detail"]

        ici = client.get("/ici", params={"lat": 46.15, "lon": -1.16})
        assert ici.status_code == 200
        body = ici.json()
        assert body.get("status") == "preparing"
        assert body.get("amp") == []
        assert body.get("poe") == []

    assert seen == []

    bi_urls: list[str] = []

    def allow_other(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if _looks_like_bi(url):
            bi_urls.append(url)
        return httpx.Response(503, json={"detail": "down"})

    async def filled():
        async with httpx.AsyncClient(transport=httpx.MockTransport(allow_other)) as client:
            return await fill_dossier(46.15, -1.16, client=client, month=6)

    bag = asyncio.run(filled())
    assert bi_urls == []
    assert bag["sources"]["bi"] == "unavailable"
    assert bag["amp"] == []
    assert bag["poe"] == []
    assert bag["projects"] == []
    assert bag["climatology"]["source"] == "zone_fallback"
    assert bag["climatology"]["kind"] == "climatology"


def test_explicit_bi_api_url_is_where_requests_go(monkeypatch):
    monkeypatch.setenv("BI_API_URL", BASE)
    monkeypatch.delenv("NAVIGUIDE_CATALOG_UPSTREAM", raising=False)
    seen: list[str] = []

    def ok(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={
            "type": "FeatureCollection",
            "features": [],
            "kind": "climatology",
            "total": 3,
        })

    _install_http_guard(monkeypatch, seen, ok)

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"type": "FeatureCollection", "features": []}

    def fake_get(url, *args, **kwargs):
        seen.append(str(url))
        return _Resp()

    monkeypatch.setattr(httpx, "get", fake_get)

    async def engine():
        async with httpx.AsyncClient() as client:
            data = await _get_json(client, f"{BASE}/amp/stats")
            return data

    assert asyncio.run(engine())["total"] == 3
    assert fetch_atlas_point(46.15, -1.16, 6)["kind"] == "climatology"
    reset_nogo_cache()
    assert load_forbidden_nogo() == []

    with TestClient(main.app) as client:
        proxy = client.get("/bi/climatology/point", params={"lat": 46.15, "lon": -1.16, "month": 6})
        assert proxy.status_code == 200
        catalog = client.get("/proxy/catalog/marinas", params={"bbox": "-5,40,10,55", "zoom": 4})
        assert catalog.status_code == 200

    assert seen, "expected upstream calls"
    assert all(url.startswith(BASE) for url in seen)
    blob = " ".join(seen)
    assert f"{BASE}/amp/stats" in blob
    assert f"{BASE}/climatology/point" in blob
    assert f"{BASE}/amp/nogo" in blob
    assert f"{BASE}/export/marinas.geojson" in blob


def test_at_most_six_bi_calls_in_flight(monkeypatch):
    monkeypatch.setenv("BI_API_URL", BASE)
    state = {"current": 0, "peak": 0, "n": 0}

    async def slow(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        state["current"] += 1
        state["peak"] = max(state["peak"], state["current"])
        try:
            await asyncio.sleep(0.2)
            return httpx.Response(200, json={"i": request.url.params.get("i")})
        finally:
            state["current"] -= 1

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
            return await asyncio.wait_for(asyncio.gather(*[
                _get_json(client, f"{BASE}/probe", params={"i": i})
                for i in range(20)
            ]), timeout=10)

    results = asyncio.run(run())
    assert state["n"] == 20
    assert state["peak"] == ici_engine._BI_PARALLEL == 6
    assert [row["i"] for row in results] == [str(i) for i in range(20)]


def test_identical_inflight_calls_share_one_upstream_request(monkeypatch):
    monkeypatch.setenv("BI_API_URL", BASE)
    state = {"n": 0}

    async def slow(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        await asyncio.sleep(0.1)
        return httpx.Response(200, json={"q": request.url.params.get("q"), "n": state["n"]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
            return await asyncio.wait_for(asyncio.gather(*[
                _get_json(client, f"{BASE}/probe", params={"q": "same"})
                for _ in range(10)
            ]), timeout=10)

    results = asyncio.run(run())
    assert state["n"] == 1
    assert len(results) == 10
    assert all(row == results[0] for row in results)
    assert results[0]["q"] == "same"


def test_inflight_failure_reaches_every_waiter_and_the_next_call_retries(monkeypatch):
    monkeypatch.setenv("BI_API_URL", BASE)
    state = {"n": 0, "fail": True}

    async def flaky(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        await asyncio.sleep(0.05)
        if state["fail"]:
            raise httpx.ConnectError("upstream down")
        return httpx.Response(200, json={"ok": True})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(flaky)) as client:
            burst = await asyncio.wait_for(asyncio.gather(*[
                _get_json(client, f"{BASE}/probe", params={"q": "same"})
                for _ in range(10)
            ], return_exceptions=True), timeout=10)
            state["fail"] = False
            again = await asyncio.wait_for(
                _get_json(client, f"{BASE}/probe", params={"q": "same"}),
                timeout=10,
            )
            return burst, again

    burst, again = asyncio.run(run())
    assert state["n"] == 2
    assert len(burst) == 10
    assert all(isinstance(item, httpx.ConnectError) for item in burst)
    assert again == {"ok": True}


def test_feature_collections_still_use_the_existing_cache(monkeypatch):
    monkeypatch.setenv("BI_API_URL", BASE)
    reset_caches()
    state = {"n": 0}
    url = f"{BASE}/export/geojson"

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        return httpx.Response(200, json={
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-1.16, 46.15]},
                "properties": {"name": "Perle"},
            }],
        })

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first = await _cached_fc(client, url)
            second = await _cached_fc(client, url)
            return first, second

    first, second = asyncio.run(run())
    assert state["n"] == 1
    assert first == second
    assert first[0]["properties"]["name"] == "Perle"
    assert url in ici_engine._fc_cache
