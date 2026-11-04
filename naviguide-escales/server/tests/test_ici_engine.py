import asyncio
import math

import httpx

from ici_engine import (
    FRENCH_EEZ_MRGID,
    PEARL_REV,
    amp_layer_sig,
    eez_plausible,
    empty_dossier,
    feature_latlon,
    fill_dossier,
    haversine_nm,
    is_fishing_amp,
    is_protected_amp,
    nearest_amp,
    nearest_places,
    parse_coord,
    pick_eez_record,
    polygon_inside_and_nm,
    radius_bbox,
    reset_caches,
    set_amp_layer_sig,
    slim_amp,
    slim_science,
    spoken_amp_name,
    thin_cache_key,
    wrap_lon,
    zee_from_record,
)
from ici_layers import (
    _seabed_label,
    attach_derived_from_science,
    aton_from_overpass,
    anchorages_from_overpass,
    climatology_rose,
    empty_satellites,
    fetch_review,
    fetch_rtofs_current,
    fetch_satellite_scene,
    geo_from_hycom,
    harbour_masters_from_overpass,
    hycom_lon,
    rtofs_from_uv,
    rtofs_is_fill,
    scene_bbox,
    slim_stac_scene,
    snapshot_ici_weather,
)
from weather_pipeline import get_pipeline


def _settle_weather(d):
    lat = d["at"]["lat"]
    lon = d["at"]["lon"]
    get_pipeline().wait_providers(
        ["openmeteo-gfs", "openmeteo-gfs-wave", "noaa-rtofs"],
        lat,
        lon,
        timeout=4.0,
    )
    d["weather"] = snapshot_ici_weather(lat, lon)
    d["sources"]["weather"] = d["weather"].get("source")
    return d

FR_EEZ = {
    "placeType": "EEZ",
    "preferredGazetteerName": "French Exclusive Economic Zone",
    "MRGID": 5677,
    "latitude": 46.07,
    "longitude": -1.96,
}


LA_ROCHELLE = (46.15, -1.16)


def _point(name, lat, lon, url=None):
    props = {"name": name, "lat": lat, "lon": lon}
    if url:
        props["source_urls"] = [url]
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": props,
    }


def test_haversine_and_bbox():
    nm = haversine_nm(46.15, -1.16, 46.15, -1.16)
    assert nm < 0.05
    # ~30 nm nord
    north = haversine_nm(46.15, -1.16, 46.65, -1.16)
    assert 29 < north < 31
    # antimeridian
    wrap = haversine_nm(0, 179.5, 0, -179.5)
    assert wrap < 70
    minx, miny, maxx, maxy = radius_bbox(46.15, -1.16, 30)
    assert minx < -1.16 < maxx
    assert miny < 46.15 < maxy
    assert maxy - miny == 1.0  # 30 nm / 60


def test_parse_coord_decimal_and_dms():
    assert parse_coord(46.15) == 46.15
    assert parse_coord("46.15") == 46.15
    assert abs(parse_coord("46°09'00\"N") - 46.15) < 0.01
    assert parse_coord(None) is None


def test_zee_from_record_and_pick():
    high = zee_from_record(None)
    assert high["name"] == "Haute mer"
    assert high["gold"] is False
    rec = {
        "placeType": "EEZ",
        "preferredGazetteerName": "French Exclusive Economic Zone",
        "MRGID": 5677,
        "latitude": 46.07,
        "longitude": -1.96,
    }
    zee = zee_from_record(rec)
    assert zee["mrgid"] == 5677
    assert zee["territory"] == "france_metropolitaine"
    assert zee["gold"] is False
    assert 5677 in FRENCH_EEZ_MRGID
    assert eez_plausible(rec, 46.15, -1.16)
    far = {
        "placeType": "EEZ",
        "preferredGazetteerName": "Brazilian Exclusive Economic Zone",
        "MRGID": 8464,
        "latitude": -11.1,
        "longitude": -39.4,
    }
    assert eez_plausible(far, 0.0, -30.0) is False
    picked = pick_eez_record([
        {"placeType": "Nation", "MRGID": 1},
        rec,
    ])
    assert picked["MRGID"] == 5677


def test_slim_science_infers_source_and_uses_props_latlon():
    cruise = {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[-2.0, 45.0], [-1.0, 46.0]]},
        "properties": {
            "name": "Campagne THALASSA",
            "kind": "cruise",
            "lat": 46.15,
            "lon": -1.16,
            "provider": "Ifremer",
        },
    }
    item = slim_science(cruise, 46.15, -1.16)
    assert item["source"] == "csr"
    assert item["kind"] == "cruise"
    assert item["provider"] == "Ifremer"
    assert item["nm"] < 1

    argo = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-1.16, 46.15]},
        "properties": {
            "name": "Argo 6901234",
            "kind": "argo_float",
            "wmo": "6901234",
            "lat": 46.15,
            "lon": -1.16,
        },
    }
    item = slim_science(argo, 46.15, -1.16)
    assert item["source"] == "argo"
    assert item["wmo"] == "6901234"


def test_nearest_places_caps_and_prefers_props_latlon():
    here_lat, here_lon = LA_ROCHELLE
    far = _point("Loin", 50.0, -5.0)
    poly = {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[-10, 40], [-10, 41], [-9, 41], [-9, 40], [-10, 40]]]},
        "properties": {"name": "Pertuis", "lat": 46.16, "lon": -1.17},
    }
    close = _point("Minimes", 46.14, -1.17, "https://douane.gouv.fr/la-rochelle")
    found = nearest_places([far, poly, close], here_lat, here_lon, 30, 5)
    assert [x["name"] for x in found] == ["Pertuis", "Minimes"]
    assert found[0]["nm"] < 5
    plat, plon = feature_latlon(poly)
    assert abs(plat - 46.16) < 0.001


def test_bi_base_defaults_to_live(monkeypatch):
    from ici_engine import bi_base

    monkeypatch.setenv("BI_API_URL", "https://blueintelligence.online/api")
    assert bi_base() == "https://blueintelligence.online/api"
    monkeypatch.setenv("BI_API_URL", "http://127.0.0.1:8001/api")
    assert bi_base() == "http://127.0.0.1:8001/api"


def test_empty_dossier_contract():
    d = empty_dossier(*LA_ROCHELLE)
    assert d["version"] == 1
    assert d["zee"] is None
    assert d["poe"] == []
    assert d["amp"] == []
    assert d["projects"] == []
    assert d["nearby"]["marinas"] == []
    assert d["polar"] is None
    assert d["science"] is None
    assert d["sources"]["bi"] is None
    assert d["climatology"] is None
    assert d["piracy"] is None
    assert d["sources"]["climatology"] is None
    assert d["nearby"]["anchorages"] == []
    assert d["satellites"]["scene"] is None
    assert d["weather"]["kind"] == "forecast"
    assert d["weather"]["wind"] is None
    assert d["emodnet"]["bathy"] is None
    assert d["aton"]["nearby"] == []
    assert d["review"]["zee"] is None


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "marineregions.org" in url:
        return httpx.Response(200, json=[FR_EEZ])
    if "poe/ports" in url:
        return httpx.Response(200, json={
            "type": "FeatureCollection",
            "features": [_point("La Rochelle", 46.15, -1.15, "https://douane.gouv.fr/la-rochelle")],
        })
    if "export/amp.geojson" in url:
        feat = _point("Pertuis charentais", 46.16, -1.20)
        feat["properties"]["visit_url"] = "https://parc-marin.fr/visite"
        feat["properties"]["manager_url"] = "https://parc-marin.fr"
        feat["properties"]["visit_url_status"] = "found"
        feat["properties"]["site_id"] = "PS-1"
        return httpx.Response(200, json={
            "type": "FeatureCollection",
            "features": [feat],
        })
    if url.endswith("/export/geojson"):
        reef = _point("Récif sentinelle", 46.18, -1.12)
        reef["properties"]["gold_on"] = True
        return httpx.Response(200, json={
            "type": "FeatureCollection",
            "features": [reef] + [
                _point(f"Projet loin {i}", 10.0, 10.0) for i in range(20)
            ],
        })
    if url.rstrip("/").endswith("/anchorages"):
        feat = _point("Mouillage des Minimes", 46.145, -1.18)
        feat["properties"]["anchorage_type"] = "anchorage"
        feat["properties"]["source"] = "osm"
        return httpx.Response(200, json={
            "type": "FeatureCollection",
            "features": [feat],
        })
    if url.rstrip("/").endswith("/marinas"):
        return httpx.Response(200, json={
            "type": "FeatureCollection",
            "features": [_point("Port des Minimes", 46.14, -1.17)],
        })
    if url.rstrip("/").endswith("/capitaineries"):
        return httpx.Response(200, json={
            "type": "FeatureCollection",
            "features": [_point("Capitainerie La Rochelle", 46.15, -1.16)],
        })
    if "export/science.geojson" in url:
        feat = _point("Pertuis bathymétrie", 46.16, -1.18, "https://sextant.ifremer.fr/x")
        feat["properties"]["source"] = "sextant"
        feat["properties"]["kind"] = "dataset"
        far = _point("Argo loin", 10.0, 10.0)
        far["properties"]["source"] = "argo"
        far["properties"]["kind"] = "argo_float"
        return httpx.Response(200, json={"type": "FeatureCollection", "features": [feat, far]})
    if "world-port-index" in url:
        return httpx.Response(200, json={
            "ports": [{"portName": "LA ROCHELLE", "latitude": 46.15, "longitude": -1.15}],
        })
    if "climatology/point" in url:
        return httpx.Response(200, json={
            "kind": "climatology",
            "month": 6,
            "period": "1980-2020",
            "doi": {"wind": "10.48670/moi-00183"},
            "wind_atlas": {
                "stat": "rose",
                "sectors_deg": 45,
                "most_likely": {"speed_knots": 16.2, "dir_deg": 55},
                "directions_from": [
                    {"dir_deg": 45, "pct": 22.0, "speed_knots": 16.2},
                    {"dir_deg": 90, "pct": 12.0, "speed_knots": 14.0},
                ],
                "calm_pct": 4.0,
                "gale_pct": 1.5,
            },
            "wave": {"hs_p50_m": 1.4, "hs_p90_m": 2.8},
            "current": {"speed_knots": 0.4, "direction_to_deg": 270},
            "cyclone": {"nearby": 0, "tracks_in_month": 4},
        })
    if "climatology/crossings" in url:
        return httpx.Response(200, json={"kind": "climatology", "count": 2})
    if "stac.dataspace.copernicus.eu" in url:
        return httpx.Response(200, json={
            "type": "FeatureCollection",
            "features": [{
                "id": "S2C_MSIL2A_20260912T110631_T30TWR",
                "collection": "sentinel-2-l2a",
                "bbox": [-1.4, 46.0, -1.0, 46.3],
                "properties": {
                    "datetime": "2026-09-12T11:06:31Z",
                    "eo:cloud_cover": 0.4,
                    "platform": "sentinel-2c",
                },
                "links": [{"rel": "self", "href": "https://stac.dataspace.copernicus.eu/v1/collections/sentinel-2-l2a/items/S2C_MSIL2A_20260912T110631_T30TWR"}],
            }],
        })
    if "marine-api.open-meteo.com" in url:
        return httpx.Response(200, json={
            "current": {
                "time": "2026-09-16T09:00",
                "wave_height": 1.1,
                "wave_direction": 270,
                "wave_period": 6.5,
            },
        })
    if "api.open-meteo.com" in url:
        return httpx.Response(200, json={
            "current": {
                "time": "2026-09-16T09:00",
                "wind_speed_10m": 12.4,
                "wind_direction_10m": 280,
            },
        })
    if "/depth" in url or "depth_sample" in url:
        return httpx.Response(200, json={"avg": 18.4, "depth_m": 18.4, "source": "emodnet-bathymetry"})
    if "emodnet-geology" in url or "seabed_substrate" in url:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"type": "FeatureCollection", "features": [{
                "type": "Feature",
                "properties": {"substrate": "sand"},
            }]},
        )
    if "emodnet-humanactivities" in url or "telecables" in url:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"type": "FeatureCollection", "features": []},
        )
    if "overpass" in url:
        body = (request.content or b"").decode("utf-8", "replace")
        if "harbour_master" in body or 'seamark:type"="anchorage' in body:
            elements = []
            if "harbour_master" in body:
                elements.append({
                    "type": "way",
                    "center": {"lat": 46.15, "lon": -1.16},
                    "tags": {"office": "harbour_master", "name": "Capitainerie La Rochelle"},
                })
            if 'seamark:type"="anchorage' in body or 'leisure"="anchorage' in body:
                elements.append({
                    "type": "node",
                    "lat": 46.145,
                    "lon": -1.18,
                    "tags": {"seamark:type": "anchorage", "name": "Mouillage des Minimes"},
                })
            return httpx.Response(200, json={"elements": elements})
        return httpx.Response(200, json={
            "elements": [{
                "type": "node",
                "lat": 46.16,
                "lon": -1.17,
                "tags": {"seamark:type": "light", "seamark:name": "Feu des Minimes"},
            }],
        })
    if "noaa/aids" in url:
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []})
    if "review/fiche" in url:
        return httpx.Response(200, json={
            "kind": "eez",
            "id": "5677",
            "gold_on": True,
            "gold_ready": True,
            "pre_gold": False,
        })
    return httpx.Response(404, json={"detail": url})


def test_fill_dossier_la_rochelle_mocked():
    reset_caches()
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return _handler(request)

    transport = httpx.MockTransport(handler)

    async def run():
        async with httpx.AsyncClient(transport=transport) as client:
            return await fill_dossier(
                46.15, -1.16, client=client, month=6, dest_lat=14.6, dest_lon=-61.0,
            )

    d = _settle_weather(asyncio.run(run()))
    assert any("/amp?" in url and "bbox=" in url for url in seen)
    assert not any("/export/marinas" in url for url in seen)
    assert any("export/amp.geojson" in url for url in seen)
    assert any("export/science.geojson" in url for url in seen)
    assert any(url.rstrip("/").endswith("/marinas") for url in seen)
    assert d["zee"]["mrgid"] == 5677
    assert d["zee"]["gold"] is True
    assert d["poe"][0]["name"] == "La Rochelle"
    assert d["poe"][0]["url"].startswith("https://douane.gouv.fr")
    assert d["amp"][0]["name"] == "Pertuis charentais"
    assert d["amp"][0]["visit_url"] == "https://parc-marin.fr/visite"
    assert d["amp"][0]["manager_url"] == "https://parc-marin.fr"
    assert d["amp"][0]["url"] == "https://parc-marin.fr/visite"
    assert d["amp"][0]["source"] == "export"
    assert d["amp"][0]["inside"] is False
    assert d["amp"][0]["siteId"] == "PS-1"
    assert d["projects"][0]["name"] == "Récif sentinelle"
    assert d["projects"][0].get("gold_on") is True
    assert len(d["projects"]) == 1
    assert d["nearby"]["marinas"][0]["name"] == "Port des Minimes"
    assert d["nearby"]["capitaineries"][0]["name"] == "Capitainerie La Rochelle"
    assert d["nearby"]["wpi"][0]["name"] == "La Rochelle"
    assert d["science"]["nearby"][0]["name"] == "Pertuis bathymétrie"
    assert d["science"]["nearby"][0]["source"] == "sextant"
    assert len(d["science"]["nearby"]) == 1
    assert d["sources"]["zee"] == "marineregions"
    assert d["sources"]["bi"] == "ok"
    assert d["depthOffshore"] is None
    assert d["sources"]["gebco"] == "coastal"
    assert "grid" not in (d.get("polar") or {})
    assert d["climatology"]["kind"] == "climatology"
    assert d["climatology"]["source"] == "atlas"
    assert d["climatology"]["point"]["wave"]["hs_p90_m"] == 2.8
    assert d["climatology"]["crossings"]["count"] == 2
    assert d["sources"]["climatology"] == "atlas"
    assert d["climatology"]["rose"]["stat"] == "rose"
    assert d["climatology"]["rose"]["calm_pct"] == 4.0
    assert d["climatology"]["rose"]["gale_pct"] == 1.5
    assert d["climatology"]["cyclone"]["nearby"] == 0
    assert d["climatology"]["current"]["direction_to_deg"] == 270
    assert d["nearby"]["anchorages"][0]["name"] == "Mouillage des Minimes"
    assert d["nearby"]["anchorages"][0]["anchorage_type"] == "anchorage"
    assert d["satellites"]["kind"] == "observation"
    assert d["satellites"]["scene"]["product"] == "sentinel-2-l2a"
    assert d["satellites"]["scene"]["datetime"].startswith("2026-09-12")
    assert d["satellites"]["derived"]["sdb"]["value"] is None
    assert d["satellites"]["derived"]["sdb"]["reason"] == "not_generated"
    assert d["weather"]["kind"] == "forecast"
    assert d["weather"]["wind"]["speedKnots"] == 12.4
    assert d["weather"]["wave"]["hs"] == 1.1
    assert d["weather"]["current"] is None
    assert (d["weather"]["current_reason"] or "").startswith("rtofs_unavailable")
    assert d["emodnet"]["bathy"]["depth_m"] == 18.4
    assert d["emodnet"]["seabed"]["label"] == "sand"
    assert d["emodnet"]["cables"]["nearby"] is False
    assert d["aton"]["nearby"][0]["name"] == "Feu des Minimes"
    assert d["review"]["zee"]["gold_on"] is True


def test_fill_dossier_thin_skips_weather_and_satellite():
    reset_caches()
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return _handler(request)

    transport = httpx.MockTransport(handler)

    async def run():
        async with httpx.AsyncClient(transport=transport) as client:
            return await fill_dossier(46.15, -1.16, client=client, month=6, thin=True)

    d = asyncio.run(run())
    assert d["zee"]["mrgid"] == 5677
    assert d["amp"]
    assert d["projects"]
    assert d["projects"][0]["name"] == "Récif sentinelle"
    assert d["nearby"]["marinas"]
    assert d["weather"]["reason"] == "not_in_along_pearl"
    assert d["satellites"]["reason"] == "not_in_along_pearl"
    assert d["climatology"] is None
    assert not any("open-meteo" in url or "dataspace.copernicus" in url for url in seen)
    assert not any("export/science.geojson" in url for url in seen)
    assert any("export/amp.geojson" in url for url in seen)
    assert any(url.rstrip("/").endswith("/export/geojson") for url in seen)


def test_thin_bag_is_cached_per_cell_for_every_visitor():
    """Les perles along sont les mêmes pour tous les visiteurs et chaque
    relecture du film : une cellule de 0,02° = un seul appel amont pendant 6 h."""
    reset_caches()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return _handler(request)

    transport = httpx.MockTransport(handler)

    async def run(lat, lon):
        async with httpx.AsyncClient(transport=transport) as client:
            return await fill_dossier(lat, lon, client=client, month=6, thin=True)

    first = asyncio.run(run(46.15, -1.16))
    n_first = len(calls)
    assert n_first > 0
    # 200 m away, same cell → no upstream call, position kept honest.
    second = asyncio.run(run(46.151, -1.161))
    assert len(calls) == n_first
    assert second["cached"] is True
    assert second["at"] == {"lat": 46.151, "lon": -1.161}
    assert second["zee"] == first["zee"]
    # Another cell → upstream again ; a full bag never reads this cache.
    asyncio.run(run(46.40, -1.16))
    assert len(calls) > n_first


def test_fill_dossier_mid_atlantic_gebco():
    reset_caches()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "opentopodata.org" in url:
            return httpx.Response(200, json={
                "results": [{"elevation": -3888.0}],
                "status": "OK",
            })
        if "marineregions.org" in url:
            return httpx.Response(200, json=[{
                "placeType": "EEZ",
                "preferredGazetteerName": "High Seas",
                "MRGID": None,
                "latitude": 35,
                "longitude": -40,
            }])
        if "world-port-index" in url:
            return httpx.Response(200, json={"ports": []})
        if "geojson" in url or url.rstrip("/").endswith("/marinas") or url.rstrip("/").endswith("/capitaineries") or "poe/ports" in url:
            return httpx.Response(200, json={"type": "FeatureCollection", "features": []})
        return httpx.Response(404, json={"detail": url})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fill_dossier(35.0, -40.0, client=client)

    d = asyncio.run(run())
    assert d["depthOffshore"] == -3888.0
    assert d["sources"]["gebco"] == "ok"


def test_fill_dossier_bi_down_keeps_zee():
    reset_caches()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "marineregions.org" in url:
            return httpx.Response(200, json=[FR_EEZ])
        if "world-port-index" in url:
            return httpx.Response(200, json={"ports": []})
        return httpx.Response(503, json={"detail": "down"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fill_dossier(46.15, -1.16, client=client)

    d = asyncio.run(run())
    assert d["zee"]["name"].startswith("French")
    assert d["zee"]["gold"] is False
    assert d["poe"] == []
    assert d["amp"] == []
    assert d["science"] is None
    assert d["sources"]["bi"] == "unavailable"


def test_fill_dossier_partial_bi_keeps_poe():
    reset_caches()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "marineregions.org" in url:
            return httpx.Response(200, json=[FR_EEZ])
        if "poe/ports" in url:
            return httpx.Response(200, json={
                "type": "FeatureCollection",
                "features": [_point("La Rochelle", 46.15, -1.15, "https://douane.gouv.fr/x")],
            })
        if "world-port-index" in url:
            return httpx.Response(200, json={"ports": []})
        return httpx.Response(500, json={"detail": "amp down"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fill_dossier(46.15, -1.16, client=client)

    d = asyncio.run(run())
    assert d["poe"][0]["name"] == "La Rochelle"
    assert d["zee"]["gold"] is True
    assert d["amp"] == []
    assert d["sources"]["bi"] == "partial"


def test_lookup_zee_inland_port_uses_offshore_probe():
    reset_caches()
    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        hits["n"] += 1
        if "/46.15000/-1.16000/" in url:
            return httpx.Response(200, json=[{
                "placeType": "Nation",
                "preferredGazetteerName": "France",
                "MRGID": 17,
            }])
        return httpx.Response(200, json=[FR_EEZ])

    async def run():
        from ici_engine import lookup_zee
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await lookup_zee(client, 46.15, -1.16)

    zee, src = asyncio.run(run())
    assert src == "marineregions"
    assert zee["mrgid"] == 5677
    assert hits["n"] >= 2


def test_lookup_zee_inland_nation_is_ashore():
    reset_caches()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{
            "placeType": "Nation",
            "preferredGazetteerName": "France",
            "MRGID": 17,
        }])

    async def run():
        from ici_engine import lookup_zee
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await lookup_zee(client, 48.81, 2.48)

    zee, src = asyncio.run(run())
    assert src == "marineregions"
    assert zee["ashore"] is True
    assert "France" in zee["name"]
    assert zee["mrgid"] is None


def test_lookup_zee_rejects_distant_gazetteer_eez():
    reset_caches()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{
            "placeType": "EEZ",
            "preferredGazetteerName": "Brazilian Exclusive Economic Zone",
            "MRGID": 8464,
            "latitude": -11.1,
            "longitude": -39.4,
        }])

    async def run():
        from ici_engine import lookup_zee
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await lookup_zee(client, 0.0, -30.0)

    zee, src = asyncio.run(run())
    assert src == "marineregions"
    assert zee["name"] == "Haute mer"
    assert zee["mrgid"] is None


def test_fill_dossier_haute_mer():
    reset_caches()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "marineregions.org" in url:
            return httpx.Response(200, json=[])
        if "world-port-index" in url:
            return httpx.Response(200, json={"ports": []})
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fill_dossier(0.0, -30.0, client=client)

    d = asyncio.run(run())
    assert d["zee"]["name"] == "Haute mer"
    assert d["zee"]["mrgid"] is None
    assert d["poe"] == []
    assert d["science"] == {"nearby": []}
    assert d["zee"]["gold"] is False


def test_chaluts_is_never_a_protected_amp():
    chaluts = {"name": "Pertuis Charentais - Chaluts", "iucn_cat": "IV", "designation": "licence"}
    petoncles = {
        "name": "Pertuis Charentais - Pétoncles - Center Pertuis Breton deposit",
        "iucn_cat": "Unassigned",
    }
    rochebonne = {"name": "Pertuis charentais - Rochebonne", "iucn_cat": "II"}
    assert is_fishing_amp(chaluts)
    assert is_fishing_amp(petoncles)
    assert not is_protected_amp(chaluts)
    assert not is_protected_amp(petoncles)
    assert is_protected_amp(rochebonne)
    feat = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-1.20, 46.16]},
        "properties": {"name": "Chaluts - Permanent prohibition zone"},
    }
    assert slim_amp(feat, 46.15, -1.16) is None
    assert spoken_amp_name(
        "Pertuis charentais - Rochebonne (IUCN Unassigned)"
    ) == "Pertuis charentais - Rochebonne"


def test_thin_bag_carries_projects_same_keys_as_full():
    """Perle thin = mêmes clés + projects (parité avec le sac ici)."""
    reset_caches()

    def handler(request: httpx.Request) -> httpx.Response:
        return _handler(request)

    transport = httpx.MockTransport(handler)

    async def run(thin, rich=False):
        async with httpx.AsyncClient(transport=transport) as client:
            return await fill_dossier(
                46.15, -1.16, client=client, month=6, thin=thin, rich=rich,
            )

    thin = asyncio.run(run(True))
    reset_caches()
    full = asyncio.run(run(False))
    assert "projects" in thin and "amp" in thin
    assert {p["name"] for p in thin["projects"]} == {p["name"] for p in full["projects"]}
    assert thin["projects"][0]["name"] == "Récif sentinelle"
    assert set(empty_dossier(46.15, -1.16)) <= set(thin)


def test_slim_amp_keeps_visit_and_manager_apart():
    feat = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-1.20, 46.16]},
        "properties": {
            "name": "Pertuis",
            "visit_url": "https://parc-marin.fr/visite",
            "manager_url": "https://parc-marin.fr",
            "visit_url_status": "found",
            "site_id": "PS-1",
        },
    }
    item = slim_amp(feat, 46.15, -1.16)
    assert item["visit_url"] != item["manager_url"]
    assert item["url"] == item["visit_url"]
    assert item["traffic"] == "unknown"


def test_slim_amp_marks_regulated():
    feat = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-1.25, 46.10], [-1.10, 46.10], [-1.10, 46.20], [-1.25, 46.20], [-1.25, 46.10],
            ]],
        },
        "properties": {
            "name": "Cabrera",
            "site_id": "AIESP1",
            "entry": 2,
            "speed": 3,
        },
    }
    item = slim_amp(feat, 46.15, -1.16)
    assert item["traffic"] == "regulated"
    assert item["entry"] == 2


def test_stac_scene_is_observation_not_forecast():
    feat = {
        "id": "S2C_MSIL2A_X",
        "collection": "sentinel-2-l2a",
        "bbox": [-1.4, 46.0, -1.0, 46.3],
        "properties": {"datetime": "2026-09-12T11:06:31Z", "eo:cloud_cover": 1.0, "platform": "sentinel-2c"},
        "links": [{"rel": "self", "href": "https://stac.example/item"}],
    }
    scene = slim_stac_scene(feat, 46.15, -1.16)
    assert scene["kind"] == "observation"
    assert scene["product"] == "sentinel-2-l2a"
    assert scene["link"] == "https://stac.example/item"
    assert "browser.dataspace.copernicus.eu" in scene["browser"]


def test_derived_satellite_stays_null_without_pilot():
    bag = attach_derived_from_science(empty_satellites(), [
        {"name": "Argo 1", "source": "argo", "kind": "argo_float"},
    ])
    assert bag["derived"]["coastline"]["value"] is None
    assert bag["derived"]["coastline"]["reason"] == "not_generated"
    filled = attach_derived_from_science(empty_satellites(), [
        {"name": "Trait de côte pilote", "source": "sentinel-pilot", "kind": "coastline", "nm": 2},
    ])
    assert filled["derived"]["coastline"]["value"]["name"] == "Trait de côte pilote"
    assert filled["derived"]["sdb"]["value"] is None


def test_climatology_rose_and_overpass_aton():
    rose = climatology_rose({
        "wind_atlas": {
            "stat": "rose",
            "directions_from": [{"dir_deg": 45, "pct": 20, "speed_knots": 12}],
            "calm_pct": 3.0,
            "gale_pct": 1.0,
        },
    })
    assert rose["stat"] == "rose"
    assert rose["calm_pct"] == 3.0
    found = aton_from_overpass(
        [{"type": "node", "lat": 46.16, "lon": -1.17,
          "tags": {"seamark:type": "light", "seamark:name": "Feu"}}],
        46.15, -1.16, haversine_nm,
    )
    assert found[0]["name"] == "Feu"
    assert found[0]["source"] == "osm-overpass"
    caps = harbour_masters_from_overpass(
        [
            {"type": "way", "center": {"lat": 46.15, "lon": -1.16},
             "tags": {"office": "harbour_master", "name": "Capitainerie La Rochelle"}},
            {"type": "node", "lat": 46.16, "lon": -1.17,
             "tags": {"seamark:type": "light", "name": "Feu"}},
        ],
        46.15, -1.16, haversine_nm,
    )
    assert [x["name"] for x in caps] == ["Capitainerie La Rochelle"]
    moor = anchorages_from_overpass(
        [{"type": "node", "lat": 46.145, "lon": -1.18,
          "tags": {"seamark:type": "anchorage", "name": "Mouillage des Minimes"}}],
        46.15, -1.16, haversine_nm,
    )
    assert moor[0]["anchorage_type"] == "anchorage"
    assert _seabed_label({"name": "Surficial sediment map"}) is None
    assert _seabed_label({"folk_5": "sand"}) == "sand"


def test_fill_dossier_overpass_when_bi_harbour_catalogs_empty():
    reset_caches()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.rstrip("/").endswith("/capitaineries") or url.rstrip("/").endswith("/anchorages"):
            return httpx.Response(200, json={"type": "FeatureCollection", "features": []})
        return _handler(request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fill_dossier(46.15, -1.16, client=client, month=6)

    d = _settle_weather(asyncio.run(run()))
    assert d["nearby"]["capitaineries"][0]["name"] == "Capitainerie La Rochelle"
    assert d["nearby"]["capitaineries"][0]["source"] == "osm-overpass"
    assert d["nearby"]["anchorages"][0]["name"] == "Mouillage des Minimes"
    assert d["sources"]["anchorages"] == "osm-overpass"


def test_fill_dossier_satellite_missing_stays_null():
    reset_caches()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "marineregions.org" in url:
            return httpx.Response(200, json=[])
        if "world-port-index" in url:
            return httpx.Response(200, json={"ports": []})
        if "stac.dataspace.copernicus.eu" in url:
            return httpx.Response(503, json={"detail": "down"})
        if "open-meteo.com" in url:
            return httpx.Response(503, json={"detail": "down"})
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fill_dossier(0.0, -30.0, client=client)

    d = _settle_weather(asyncio.run(run()))
    assert d["satellites"]["scene"] is None
    assert d["satellites"]["kind"] == "observation"
    assert "cdse_stac_unavailable" in (d["satellites"]["reason"] or "")
    assert d["satellites"]["derived"]["coastline"]["value"] is None
    assert d["weather"]["kind"] == "forecast"
    assert d["weather"]["wind"] is None
    assert "openmeteo_unavailable" in (d["weather"]["reason"] or "")


def test_fill_dossier_aton_us_uses_noaa():
    reset_caches()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "marineregions.org" in url:
            return httpx.Response(200, json=[])
        if "world-port-index" in url:
            return httpx.Response(200, json={"ports": []})
        if "noaa/aids" in url:
            return httpx.Response(200, json={
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-76.0, 37.0]},
                    "properties": {"name": "Chesapeake Light", "kind": "light", "source": "noaa"},
                }],
            })
        if "overpass" in url:
            return httpx.Response(200, json={"elements": []})
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fill_dossier(37.0, -76.0, client=client)

    d = asyncio.run(run())
    assert d["aton"]["nearby"][0]["name"] == "Chesapeake Light"
    assert d["aton"]["source"] == "noaa-enc"


def test_scene_bbox_does_not_cross_antimeridian():
    box = scene_bbox(0.0, 179.8, 30.0)
    assert box[0] >= -180.0
    assert box[2] <= 180.0
    assert box[0] < box[2]
    west = scene_bbox(0.0, -179.8, 30.0)
    assert west[0] >= -180.0
    assert west[2] <= 180.0
    assert west[0] < west[2]


def test_rtofs_hycom_wrap_and_fill():
    assert abs(hycom_lon(-30.0) - 330.0) < 1e-6
    assert abs(hycom_lon(0.0) - 360.0) < 1e-6
    assert abs(hycom_lon(179.8) - 179.8) < 1e-6
    assert abs(hycom_lon(-180.0) - 180.0) < 1e-6
    assert abs(geo_from_hycom(330.0) + 30.0) < 1e-6
    assert rtofs_is_fill(1.2676506e30)
    assert rtofs_is_fill(None)
    assert not rtofs_is_fill(0.12)
    cur = rtofs_from_uv(0.15, -0.08, issued="2026-09-16T00:00:00Z")
    assert cur["kind"] == "forecast"
    assert cur["source"] == "noaa-rtofs"
    assert cur["speedKnots"] > 0
    assert 0 <= cur["dirToDeg"] < 360


def test_fetch_rtofs_listing_404_is_unavailable_not_not_ingested():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": str(request.url)})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_rtofs_current(client, 0.0, -30.0)

    current, reason = asyncio.run(run())
    assert current is None
    assert reason.startswith("rtofs_unavailable")
    assert "not_ingested" not in reason


def test_fill_dossier_rtofs_forecast_when_model_answers(monkeypatch):
    reset_caches()

    async def fake_rtofs(client, lat, lon):
        return {
            "kind": "forecast",
            "source": "noaa-rtofs",
            "speedKnots": 0.58,
            "dirToDeg": 247.0,
            "issued": "2026-09-16T00:00:00Z",
            "product": "rtofs_glo_2ds_n000_prog.nc",
        }, None

    monkeypatch.setattr("ici_layers.fetch_rtofs_current", fake_rtofs)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
            return await fill_dossier(0.0, -30.0, client=client)

    d = _settle_weather(asyncio.run(run()))
    assert d["weather"]["current"]["kind"] == "forecast"
    assert d["weather"]["current"]["source"] == "noaa-rtofs"
    assert d["weather"]["current"]["speedKnots"] == 0.58
    assert d["weather"]["current_reason"] is None


def test_fill_dossier_rtofs_off_grid(monkeypatch):
    reset_caches()

    async def fake_rtofs(client, lat, lon):
        return None, "off_grid"

    monkeypatch.setattr("ici_layers.fetch_rtofs_current", fake_rtofs)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
            return await fill_dossier(46.15, -1.16, client=client)

    d = _settle_weather(asyncio.run(run()))
    assert d["weather"]["current"] is None
    assert d["weather"]["current_reason"] == "off_grid"
    assert d["weather"]["wind"]["speedKnots"] == 12.4


def test_stac_200_empty_is_not_catalog_mute():
    def handler(request: httpx.Request) -> httpx.Response:
        if "stac.dataspace.copernicus.eu" in str(request.url):
            return httpx.Response(200, json={"type": "FeatureCollection", "features": []})
        return httpx.Response(404)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_satellite_scene(client, 0.0, -30.0)

    bag = asyncio.run(run())
    assert bag["http_status"] == 200
    assert bag["url"] == "https://stac.dataspace.copernicus.eu/v1/search"
    assert bag["scene"] is None
    assert bag["reason"] == "no_scene_in_bbox"
    assert "unavailable" not in (bag["reason"] or "")


def test_stac_down_records_status_and_url():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "down"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_satellite_scene(client, 24.0, 36.5)

    bag = asyncio.run(run())
    assert bag["scene"] is None
    assert bag["http_status"] == 503
    assert bag["url"] == "https://stac.dataspace.copernicus.eu/v1/search"
    assert "cdse_stac_unavailable:503" in (bag["reason"] or "")


def test_review_401_is_admin_not_no_eez():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Admin key required"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_review(
                client,
                "https://blueintelligence.online/api",
                {"name": "French Exclusive Economic Zone", "mrgid": 5677},
                None,
            )

    bag = asyncio.run(run())
    assert bag["zee"] is None
    assert bag["reason"] == "review_requires_admin"
    assert bag["http_status"] == 401
    assert bag["url"]
    assert "no_entity" not in (bag["reason"] or "")


def test_review_sends_bi_admin_key_when_configured(monkeypatch):
    """`BI_ADMIN_KEY` (simulator.env) → X-Admin-Key vers BI : la fiche Gold
    revient au lieu de « réservée à l'administration »."""
    monkeypatch.setenv("BI_ADMIN_KEY", "sesame-bi")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["admin"] = request.headers.get("X-Admin-Key")
        return httpx.Response(200, json={"gold_on": True, "gold_ready": True, "pre_gold": False})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_review(
                client,
                "https://blueintelligence.online/api",
                {"name": "French Exclusive Economic Zone", "mrgid": 5677},
                None,
            )

    bag = asyncio.run(run())
    assert seen["admin"] == "sesame-bi"
    assert bag["zee"]["gold_on"] is True
    assert bag["reason"] is None

    monkeypatch.delenv("BI_ADMIN_KEY", raising=False)
    from ici_layers import bi_review_headers
    assert "X-Admin-Key" not in bi_review_headers()


def test_review_high_seas_no_entity_without_fiche():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(401, json={"detail": "Admin key required"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_review(client, "https://blueintelligence.online/api", {"name": "Haute mer", "mrgid": None}, None)

    bag = asyncio.run(run())
    assert bag["reason"] == "no_entity"
    assert bag["zee"] is None
    assert not any("review/fiche" in url for url in seen)


def test_route_events_project_10nm_not_60nm():
    """Un projet à 10 nm produit un événement ; à 60 nm aucun. Chaluts n'est pas une AMP."""
    import ici_engine
    import ici_warm
    from ici_engine import thin_cache_key

    reset_caches()
    points = [
        {"lat": 46.15, "lon": -1.16, "cumNm": 0, "filmCum": 0},
        {"lat": 46.15, "lon": -1.40, "cumNm": 12, "filmCum": 12},
        {"lat": 46.15, "lon": -1.64, "cumNm": 24, "filmCum": 24},
    ]
    pearls = ici_warm.sample_route_nm(points)
    assert pearls
    p0 = pearls[0]
    ici_engine.thin_cache_put(thin_cache_key(p0["lat"], p0["lon"], 30.0), {
        "zee": None,
        "amp": [
            {"name": "Chaluts", "site_id": "ch-1", "nm": 2.0},
            {"name": "Pertuis charentais - Rochebonne", "site_id": "rb-1", "nm": 8.0, "iucn_cat": "II"},
        ],
        "projects": [
            {"name": "Récif sentinelle", "nm": 10.0, "gold_on": True},
            {"name": "Hors portée", "nm": 60.0, "gold_on": True},
        ],
        "sources": {"bi": "ok"},
    })
    events = ici_warm.route_events_from_pearls(points)
    amps = [e for e in events if e["kind"] == "amp"]
    projs = [e for e in events if e["kind"] == "project"]
    assert [e["name"] for e in amps] == ["Pertuis charentais - Rochebonne"]
    assert not any("Chaluts" in (e.get("name") or "") for e in amps)
    assert [e["name"] for e in projs] == ["Récif sentinelle"]
    assert not any(e["name"] == "Hors portée" for e in projs)


def _square_poly(lat_c, lon_c, half_nm):
    dlat = half_nm / 60.0
    dlon = half_nm / (60.0 * math.cos(math.radians(lat_c)))
    ring = [
        [lon_c - dlon, lat_c - dlat],
        [lon_c + dlon, lat_c - dlat],
        [lon_c + dlon, lat_c + dlat],
        [lon_c - dlon, lat_c + dlat],
        [lon_c - dlon, lat_c - dlat],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def _amp_poly_feat(name, geom, lat, lon, site_id="PS-x"):
    return {
        "type": "Feature",
        "id": site_id,
        "geometry": geom,
        "properties": {"name": name, "lat": lat, "lon": lon, "site_id": site_id},
    }


def test_amp_polygon_inside_nm_zero():
    lat, lon = 41.31, 9.19
    geom = _square_poly(lat, lon, 20)
    inside, nm, _area = polygon_inside_and_nm(geom, lat, lon)
    assert inside is True
    assert nm == 0.0
    feat = _amp_poly_feat("Bouches de Bonifacio", geom, lat, lon, "boni-1")
    found = nearest_amp([feat], lat, lon, 30, source="polygon")
    assert len(found) == 1
    assert found[0]["inside"] is True
    assert found[0]["nm"] == 0.0
    assert found[0]["source"] == "polygon"
    assert found[0]["siteId"] == "boni-1"


def test_amp_polygon_10nm_from_edge_60nm_from_centroid():
    """Parc ~100 nm : le bateau est à 10 nm du bord, 60 nm du centroïde."""
    lat_c, lon_c = 46.0, 0.0
    geom = _square_poly(lat_c, lon_c, 50)
    dlon_10 = 10.0 / (60.0 * math.cos(math.radians(lat_c)))
    dlon_50 = 50.0 / (60.0 * math.cos(math.radians(lat_c)))
    lat, lon = lat_c, lon_c - dlon_50 - dlon_10
    to_c = haversine_nm(lat, lon, lat_c, lon_c)
    assert 58 < to_c < 62
    inside, nm, _area = polygon_inside_and_nm(geom, lat, lon)
    assert inside is False
    assert 8.5 <= nm <= 11.5
    feat = _amp_poly_feat("Grand parc", geom, lat_c, lon_c, "gp-1")
    found = nearest_amp([feat], lat, lon, 15, source="polygon")
    assert found and found[0]["inside"] is False
    assert 8.5 <= found[0]["nm"] <= 11.5
    assert found[0]["source"] == "polygon"
    old = nearest_places([feat], lat, lon, 15, 5, slim=slim_amp)
    assert old == []


def test_amp_polygon_centroid_10nm_edge_30nm():
    """Le centroïde exporté est à 10 nm ; le bord du polygone est à 30 nm."""
    lat0, lon0 = 46.0, 0.0
    k = 60.0 * math.cos(math.radians(lat0))
    lon_cent = lon0 + 10.0 / k
    lon_poly = lon0 + 35.0 / k
    geom = _square_poly(lat0, lon_poly, 5)
    inside, nm, _area = polygon_inside_and_nm(geom, lat0, lon0)
    assert inside is False
    assert 28.5 <= nm <= 31.5
    feat = _amp_poly_feat("Parc décalé", geom, lat0, lon_cent, "dec-1")
    found = nearest_amp([feat], lat0, lon0, 40, source="polygon")
    assert found[0]["nm"] >= 28.5
    old = slim_amp(feat, lat0, lon0)
    assert 8.5 <= old["nm"] <= 11.5


def test_amp_sort_inside_then_nm():
    lat, lon = 46.15, -1.16
    inside_a = _amp_poly_feat("Dedans A", _square_poly(lat, lon, 8), lat, lon, "in-a")
    inside_b = _amp_poly_feat("Dedans B", _square_poly(lat, lon, 12), lat, lon, "in-b")
    dlon_2 = 2.0 / (60.0 * math.cos(math.radians(lat)))
    dlon_8 = 8.0 / (60.0 * math.cos(math.radians(lat)))
    near = _amp_poly_feat(
        "Proche", _square_poly(lat, lon + dlon_2 + 0.5 / (60.0 * math.cos(math.radians(lat))), 0.5),
        lat, lon + dlon_2, "out-2",
    )
    far = _amp_poly_feat(
        "Loin", _square_poly(lat, lon + dlon_8 + 0.5 / (60.0 * math.cos(math.radians(lat))), 0.5),
        lat, lon + dlon_8, "out-8",
    )
    found = nearest_amp([far, inside_b, near, inside_a], lat, lon, 30, source="polygon")
    names = [x["name"] for x in found]
    assert names[:2] == ["Dedans A", "Dedans B"]  # plus petit polygone d'abord
    assert found[0]["inside"] and found[1]["inside"]
    assert found[2]["name"] == "Proche"
    assert found[3]["name"] == "Loin"
    assert found[2]["nm"] < found[3]["nm"]


def test_amp_jurisdiction_layers_are_dropped():
    lat, lon = 41.31, 9.19
    sea = _amp_poly_feat("France Territorial Sea", _square_poly(lat, lon, 80), lat, lon, "ts-1")
    iccat = _amp_poly_feat(
        "International Commission for the Conservation of Atlantic Tunas",
        _square_poly(lat, lon, 90), lat, lon, "iccat-1",
    )
    iotc = _amp_poly_feat(
        "Indian Ocean Tuna Commission",
        _square_poly(lat, lon, 85), lat, lon, "iotc-1",
    )
    park = _amp_poly_feat("Strait of Bonifacio", _square_poly(lat, lon, 8), lat, lon, "boni-strait")
    found = nearest_amp([sea, iccat, iotc, park], lat, lon, 30, source="polygon")
    assert [x["name"] for x in found] == ["Strait of Bonifacio"]
    assert found[0]["inside"] is True


def test_amp_polygon_unwraps_voyage_longitude():
    lat, lon_w = -22.30, 166.46
    geom = _square_poly(lat, lon_w, 20)
    assert abs(wrap_lon(lon_w - 360.0) - lon_w) < 0.01
    inside, nm, _area = polygon_inside_and_nm(geom, lat, lon_w - 360.0)
    assert inside is True
    assert nm == 0.0
    feat = _amp_poly_feat("Natural Park of the Coral Sea", geom, lat, lon_w, "nc-1")
    found = nearest_amp([feat], lat, lon_w - 360.0, 30, source="polygon")
    assert found and found[0]["inside"] is True


def test_amp_fallback_export_when_get_amp_errors():
    reset_caches()
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        url = str(request.url)
        if "/amp?" in url and "bbox=" in url:
            return httpx.Response(503, json={"detail": "amp down"})
        return _handler(request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fill_dossier(46.15, -1.16, client=client, thin=True)

    d = asyncio.run(run())
    assert any("/amp?" in url and "bbox=" in url for url in seen)
    assert any("export/amp.geojson" in url for url in seen)
    assert d["amp"][0]["name"] == "Pertuis charentais"
    assert d["amp"][0]["source"] == "export"
    assert d["amp"][0]["inside"] is False
    assert d["amp"][0]["siteId"] == "PS-1"
    assert d["amp"][0].get("visitUrl") == "https://parc-marin.fr/visite"


def test_amp_empty_get_amp_falls_back_to_export():
    """Un 200 /amp vide n'est plus figé — repli export, comme un 5xx."""
    reset_caches()
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        url = str(request.url)
        if "/amp?" in url and "bbox=" in url:
            return httpx.Response(200, json={"type": "FeatureCollection", "features": []})
        if "/amp/stats" in url:
            return httpx.Response(200, json={"total": 3769})
        return _handler(request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fill_dossier(46.15, -1.16, client=client, thin=True)

    d = asyncio.run(run())
    assert any("/amp?" in url and "bbox=" in url for url in seen)
    assert any("export/amp.geojson" in url for url in seen)
    assert d["amp"][0]["name"] == "Pertuis charentais"
    assert d["amp"][0]["source"] == "export"
    assert d["amp"][0]["inside"] is False
    assert d["amp"][0]["siteId"] == "PS-1"


def test_amp_polygon_from_get_amp_fill_dossier():
    reset_caches()
    lat, lon = 41.31, 9.19
    geom = _square_poly(lat, lon, 15)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        url = str(request.url)
        if "/amp/stats" in url:
            return httpx.Response(200, json={"total": 3769})
        if "/amp?" in url and "bbox=" in url:
            feat = _amp_poly_feat("Réserve naturelle des Bouches de Bonifacio", geom, lat, lon, "boni-1")
            feat["properties"]["visit_url"] = "https://www.bonifacio.fr"
            return httpx.Response(200, json={"type": "FeatureCollection", "features": [feat]})
        return _handler(request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fill_dossier(lat, lon, client=client, thin=True)

    d = asyncio.run(run())
    assert d["amp"][0]["inside"] is True
    assert d["amp"][0]["nm"] == 0.0
    assert d["amp"][0]["source"] == "polygon"
    assert "Bonifacio" in d["amp"][0]["name"]
    assert not any("export/amp.geojson" in url for url in seen)


def test_thin_cache_key_changes_with_amp_signature():
    reset_caches()
    assert amp_layer_sig() == "0"
    k0 = thin_cache_key(46.15, -1.16, 30)
    set_amp_layer_sig(3769)
    k1 = thin_cache_key(46.15, -1.16, 30)
    set_amp_layer_sig(4000)
    k2 = thin_cache_key(46.15, -1.16, 30)
    assert k0 != k1 != k2
    assert k0.endswith(":a0")
    assert k1.endswith(":a3769")
    assert k2.endswith(":a4000")
    assert k0.rsplit(":a", 1)[0] == k1.rsplit(":a", 1)[0]
    assert f":{PEARL_REV}:" in k0
    reset_caches()


def test_thin_cache_key_changes_with_pearl_rev(monkeypatch):
    import ici_engine
    reset_caches()
    k0 = thin_cache_key(46.15, -1.16, 30)
    assert PEARL_REV in k0.split(":")
    monkeypatch.setattr(ici_engine, "PEARL_REV", "am1a-x")
    k1 = thin_cache_key(46.15, -1.16, 30)
    assert k0 != k1
    assert "am1a-x" in k1.split(":")
    reset_caches()
