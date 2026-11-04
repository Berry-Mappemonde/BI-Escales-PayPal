import asyncio

import httpx

from gebco_lookup import (
    COASTAL_CUTOFF_NM,
    attach_depth_offshore,
    min_coast_nm,
    reset_gebco_cache,
)


def test_min_coast_nm_uses_ports_only():
    d = {
        "nearby": {
            "marinas": [{"name": "Minimes", "nm": 4.2}],
            "capitaineries": [],
            "wpi": [{"name": "LA ROCHELLE", "nm": 1.1}],
        },
        "amp": [{"name": "loin", "nm": 800}],
    }
    assert min_coast_nm(d) == 1.1
    assert min_coast_nm(d) < COASTAL_CUTOFF_NM
    assert min_coast_nm({"nearby": {}}) is None


def test_attach_coastal_skips_upstream():
    reset_gebco_cache()
    hits = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        return httpx.Response(200, json={"results": [{"elevation": -3200}]})

    d = {
        "at": {"lat": 46.15, "lon": -1.16},
        "nearby": {"marinas": [{"nm": 2.0}], "capitaineries": [], "wpi": []},
        "sources": {},
    }

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await attach_depth_offshore(d, client)

    asyncio.run(run())
    assert d["depthOffshore"] is None
    assert d["sources"]["gebco"] == "coastal"
    assert hits["n"] == 0


def test_attach_offshore_records_gebco_sounding():
    reset_gebco_cache()

    def handler(request: httpx.Request) -> httpx.Response:
        assert "opentopodata.org" in str(request.url)
        return httpx.Response(200, json={
            "results": [{"elevation": -3888.0, "dataset": "gebco2020"}],
            "status": "OK",
        })

    d = {
        "at": {"lat": 35.0, "lon": -40.0},
        "nearby": {"marinas": [], "capitaineries": [], "wpi": []},
        "sources": {},
    }

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await attach_depth_offshore(d, client)

    asyncio.run(run())
    assert d["depthOffshore"] == -3888.0
    assert d["sources"]["gebco"] == "ok"


def test_attach_land_is_null():
    reset_gebco_cache()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"elevation": 12.0}]})

    d = {
        "at": {"lat": 46.15, "lon": -1.16},
        "nearby": {"marinas": [], "capitaineries": [], "wpi": []},
        "sources": {},
    }

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await attach_depth_offshore(d, client)

    asyncio.run(run())
    assert d["depthOffshore"] is None
    assert d["sources"]["gebco"] == "land"
