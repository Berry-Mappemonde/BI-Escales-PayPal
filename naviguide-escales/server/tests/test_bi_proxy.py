"""Passerelle /bi/climatology/* — une requête amont par cellule et par machine."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

import bi_proxy
import main


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_BI_CACHE_DIR", str(tmp_path / "bi-cache"))
    bi_proxy.reset()
    yield
    bi_proxy.reset()


def _upstream(calls, status=200, body=None, delay=0.0):
    payload = json.dumps(body or {"kind": "climatology", "month": 9}).encode()

    async def fake(url, params):
        calls.append((url, tuple(params)))
        if delay:
            await asyncio.sleep(delay)
        return status, payload
    return fake


def test_miss_then_hit_calls_upstream_once(monkeypatch):
    calls = []
    monkeypatch.setattr(bi_proxy, "fetch_upstream", _upstream(calls))
    client = TestClient(main.app)

    first = client.get("/bi/climatology/point?lat=46.15&lon=-1.2&month=9")
    second = client.get("/bi/climatology/point?month=9&lon=-1.2&lat=46.15")  # même cellule, autre ordre

    assert first.status_code == 200 and second.status_code == 200
    assert first.headers["x-cache-status"] == "MISS"
    assert second.headers["x-cache-status"] == "HIT"
    assert "max-age=" in first.headers["cache-control"]
    assert first.json()["kind"] == "climatology"
    assert len(calls) == 1
    assert calls[0][0].endswith("/api/climatology/point")


def test_only_climatology_endpoints_are_proxied(monkeypatch):
    calls = []
    monkeypatch.setattr(bi_proxy, "fetch_upstream", _upstream(calls))
    client = TestClient(main.app)
    assert client.get("/bi/climatology/review/fiche?kind=eez&id=1").status_code == 404
    assert client.get("/bi/marinas").status_code == 404
    assert client.get("/bi/climatology/crossings?lat1=1&lon1=2&lat2=3&lon2=4&month=9").status_code == 200
    assert len(calls) == 1


def test_tile_paths_are_proxied_and_bad_paths_are_refused(monkeypatch):
    calls = []
    monkeypatch.setattr(bi_proxy, "fetch_upstream", _upstream(calls))
    client = TestClient(main.app)
    ok = client.get("/bi/climatology/wind/tiles/4/8/5.json?month=9")
    assert ok.status_code == 200
    assert calls[0][0].endswith("/api/climatology/wind/tiles/4/8/5.json")
    assert client.get("/bi/climatology/wave/tiles/3/2/1.json?month=1&stat=p90").status_code == 200
    assert client.get("/bi/climatology/current/tiles/0/0/0.json?month=6").status_code == 200
    assert client.get("/bi/climatology/wind/tiles/foo/1/1.json").status_code == 404
    assert client.get("/bi/climatology/cyclones/tiles/1/1/1.json").status_code == 404
    assert client.get("/bi/climatology/wind/tiles/4/8/5.geojson").status_code == 404
    assert client.get("/bi/climatology/wind/tiles/4/8/5.json/extra").status_code == 404
    assert len(calls) == 3


def test_offline_returns_quiet_empty_not_502(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_OFFLINE", "1")
    client = TestClient(main.app)
    r = client.get("/bi/climatology/point?lat=1&lon=2&month=9")
    assert r.status_code == 200
    assert r.json()["kind"] == "unavailable"
    assert r.headers["x-cache-status"] == "OFFLINE"


def test_upstream_5xx_opens_a_cooldown_and_is_not_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(bi_proxy, "fetch_upstream", _upstream(calls, status=502))
    client = TestClient(main.app)

    # Consigne du 18 oct. 2026 : 200 {"status":"unavailable"} au lieu d'un 502.
    down = client.get("/bi/climatology/point?lat=1&lon=2&month=9")
    assert down.status_code == 200
    assert down.json()["status"] == "unavailable"
    assert bi_proxy.is_dead()
    # Rafale pendant la panne : zéro appel amont supplémentaire.
    for _ in range(20):
        again = client.get("/bi/climatology/point?lat=1&lon=2&month=9")
        assert again.status_code == 200
        assert again.json()["status"] == "unavailable"
    assert len(calls) == 1
    # Panne finie, amont revenu : on redemande (rien n'a été mis en cache).
    bi_proxy.reset()
    monkeypatch.setattr(bi_proxy, "fetch_upstream", _upstream(calls))
    assert client.get("/bi/climatology/point?lat=1&lon=2&month=9").headers["x-cache-status"] == "MISS"
    assert len(calls) == 2


def test_layer_failure_does_not_block_points(monkeypatch):
    """22 sept. : wind.geojson (26 Mo, ~18 s) dépassait le délai et marquait tout l'atlas mort 30 s →
    3 762 × 502 sur `point` alors que l'atlas répondait. Le repos est par point d'accès."""
    calls = []
    ok = _upstream(calls)

    async def upstream(url, params):
        if url.endswith("/wind.geojson"):
            raise TimeoutError("read timeout")
        return await ok(url, params)
    monkeypatch.setattr(bi_proxy, "fetch_upstream", upstream)
    client = TestClient(main.app)

    wind = client.get("/bi/climatology/wind.geojson?month=9")
    assert wind.status_code == 200
    assert wind.json()["status"] == "unavailable"
    assert bi_proxy.is_dead("wind.geojson")
    assert not bi_proxy.is_dead("point")
    r = client.get("/bi/climatology/point?lat=46.15&lon=-1.2&month=9")
    assert r.status_code == 200 and r.headers["x-cache-status"] == "MISS"
    assert client.get("/bi/climatology/crossings?lat1=1&lon1=2&lat2=3&lon2=4&month=9").status_code == 200
    # La couche, elle, reste en repos : pas de nouvel appel amont pendant 30 s.
    again = client.get("/bi/climatology/wind.geojson?month=9")
    assert again.status_code == 200
    assert again.json()["status"] == "unavailable"
    assert len(calls) == 2


def test_layers_get_a_longer_timeout_than_points():
    assert bi_proxy.timeout_for("point") == bi_proxy.TIMEOUT_S
    assert bi_proxy.timeout_for("https://blueintelligence.online/api/climatology/wind.geojson") == bi_proxy.LAYER_TIMEOUT_S
    assert bi_proxy.LAYER_TIMEOUT_S >= 60 > bi_proxy.TIMEOUT_S


def test_cache_is_per_machine_not_per_checkout(monkeypatch):
    from pathlib import Path
    monkeypatch.delenv("NAVIGUIDE_BI_CACHE_DIR", raising=False)
    d = bi_proxy.cache_dir()
    assert Path.home() in d.parents
    assert ".dev" not in d.parts


def test_network_error_is_unavailable_not_a_500(monkeypatch):
    async def boom(url, params):
        raise ConnectionError("refused")
    monkeypatch.setattr(bi_proxy, "fetch_upstream", boom)
    client = TestClient(main.app)
    r = client.get("/bi/climatology/point?lat=1&lon=2&month=9")
    assert r.status_code == 200
    assert r.status_code != 500
    assert r.json()["status"] == "unavailable"


def test_upstream_4xx_is_passed_through_and_not_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(bi_proxy, "fetch_upstream", _upstream(calls, status=400, body={"detail": "lat/lon out of range"}))
    client = TestClient(main.app)
    assert client.get("/bi/climatology/point?lat=95&lon=2&month=9").status_code == 400
    assert client.get("/bi/climatology/point?lat=95&lon=2&month=9").status_code == 400
    assert len(calls) == 2
    assert not bi_proxy.is_dead()


def test_twin_requests_in_flight_share_one_upstream_call(monkeypatch):
    calls = []
    monkeypatch.setattr(bi_proxy, "fetch_upstream", _upstream(calls, delay=0.05))

    async def burst():
        from httpx import ASGITransport, AsyncClient
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://t") as c:
            return await asyncio.gather(*[
                c.get("/bi/climatology/point?lat=46.15&lon=-1.2&month=9") for _ in range(25)
            ])

    responses = asyncio.run(burst())
    assert all(r.status_code == 200 for r in responses)
    assert len(calls) == 1
    assert sum(1 for r in responses if r.headers["x-cache-status"] == "MISS") == 1


def test_outage_serves_the_last_good_response(monkeypatch):
    """Panne après une réponse bonne : on ressert ce corps, pas une erreur."""
    calls = []
    monkeypatch.setattr(bi_proxy, "fetch_upstream", _upstream(calls, body={"kind": "climatology", "period": "1993-2021"}))
    client = TestClient(main.app)
    first = client.get("/bi/climatology/point?lat=10&lon=20&month=6")
    assert first.status_code == 200 and first.headers["x-cache-status"] == "MISS"
    monkeypatch.setattr(bi_proxy, "TTL_S", 0)  # la copie fraîche est périmée
    monkeypatch.setattr(bi_proxy, "fetch_upstream", _upstream(calls, status=503))
    bi_proxy.reset()  # lève le repos, pas le fichier
    stale = client.get("/bi/climatology/point?lat=10&lon=20&month=6")
    assert stale.status_code == 200
    assert stale.headers["x-cache-status"] == "STALE"
    assert stale.json()["period"] == "1993-2021"
    assert stale.json()["kind"] == "climatology"


def test_bi_down_without_cache_is_200_unavailable(monkeypatch):
    calls = []
    monkeypatch.setattr(bi_proxy, "fetch_upstream", _upstream(calls, status=502))
    client = TestClient(main.app)
    r = client.get("/bi/climatology/meta?month=9")
    assert r.status_code == 200
    assert r.json() == {"status": "unavailable"}
    assert r.headers["x-cache-status"] == "UNAVAILABLE"
    assert len(calls) == 1


def test_vite_proxy_never_targets_production_by_default():
    from pathlib import Path
    cfg = (Path(__file__).resolve().parents[2] / "vite.config.js").read_text(encoding="utf-8")
    assert "process.env.BI_PROXY_TARGET\n" in cfg or "process.env.BI_PROXY_TARGET" in cfg
    # La cible par défaut de /bi est l'API locale, pas blueintelligence.online.
    assert ': { target: API, changeOrigin: true }' in cfg
    assert 'target: process.env.BI_PROXY_TARGET || "https://blueintelligence.online"' not in cfg
