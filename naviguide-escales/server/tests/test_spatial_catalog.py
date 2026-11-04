import pytest

from spatial_catalog import Bbox, SpatialCatalogIndex, parse_bbox


def point(lon, lat, **properties):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": properties,
    }


def test_index_filters_bbox_and_science_source_across_antimeridian():
    index = SpatialCatalogIndex("science", [
        point(175, 0, source="argo", name="Fidji Est"),
        point(-175, 0, source="argo", name="Fidji Ouest"),
        point(0, 0, source="sextant", name="Greenwich"),
    ])

    result = index.query(Bbox(170, -10, -170, 10), zoom=8, source="argo")

    assert {feature["properties"]["name"] for feature in result["features"]} == {"Fidji Est", "Fidji Ouest"}
    assert all(feature["properties"]["naviguideCatalogId"].startswith("science:") for feature in result["features"])
    assert result["metadata"]["matched"] == 2
    assert result["metadata"]["total"] == 2


def test_index_clusters_points_to_zoom_budget_without_losing_count():
    index = SpatialCatalogIndex("ports", [
        point(-4 + (position % 40) / 10, 45 + (position // 40) / 10, name=f"Port {position}")
        for position in range(1_000)
    ])

    result = index.query(Bbox(-5, 44, 1, 48), zoom=2, limit=420)

    assert len(result["features"]) <= 80
    assert sum(feature["properties"].get("clusterCount", 1) for feature in result["features"]) == 1_000
    assert result["metadata"]["clustered"] is True


def test_empty_catalog_reports_total_zero_not_a_quiet_viewport():
    index = SpatialCatalogIndex("capitaineries", [])
    result = index.query(Bbox(-10, 40, 10, 50), zoom=4)
    assert result["features"] == []
    assert result["metadata"]["matched"] == 0
    assert result["metadata"]["total"] == 0

    full = SpatialCatalogIndex("capitaineries", [point(140, -35, name="Sydney")])
    ocean = full.query(Bbox(-10, 40, 10, 50), zoom=4)
    assert ocean["features"] == []
    assert ocean["metadata"]["matched"] == 0
    assert ocean["metadata"]["total"] == 1


def test_cluster_does_not_carry_one_point_contact():
    index = SpatialCatalogIndex("marinas", [
        {**point(-4 + (position % 40) / 10, 45 + (position // 40) / 10, name=f"Port {position}"),
         "properties": {"name": f"Port {position}", "website": f"https://example.org/{position}", "telephone": "+33 5", "url": "https://example.org/u"}}
        for position in range(1_000)
    ])
    result = index.query(Bbox(-5, 44, 1, 48), zoom=2, limit=420)
    clusters = [f for f in result["features"] if f["properties"].get("clusterCount", 1) > 1]
    assert clusters
    for feature in clusters:
        for key in ("website", "telephone", "url"):
            assert key not in feature["properties"], key


def test_cluster_point_only_props_match_the_client():
    import pathlib
    import re

    import spatial_catalog

    source = (pathlib.Path(spatial_catalog.__file__).parent.parent / "src" / "layers" / "spatialFeatures.js").read_text(encoding="utf-8")
    block = re.search(r"const POINT_ONLY_PROPS = \[(.*?)\];", source, re.S)
    assert block, "POINT_ONLY_PROPS not found in spatialFeatures.js"
    client = set(re.findall(r'"([^"]+)"', block.group(1)))
    assert "name" in spatial_catalog.CLUSTER_POINT_ONLY_PROPS
    assert set(spatial_catalog.CLUSTER_POINT_ONLY_PROPS) == client


def test_cluster_is_named_by_its_count_not_by_one_point():
    index = SpatialCatalogIndex("marinas", [
        {**point(-4 + (position % 40) / 10, 45 + (position // 40) / 10, name=f"Port {position}"),
         "properties": {"name": f"Port {position}"}}
        for position in range(1_000)
    ])
    result = index.query(Bbox(-5, 44, 1, 48), zoom=2, limit=420)
    clusters = [f for f in result["features"] if f["properties"].get("clusterCount", 1) > 1]
    assert clusters
    for feature in clusters:
        props = feature["properties"]
        assert not str(props.get("name", "")).startswith("Port "), props.get("name")
        assert props["name"] == f"{props['clusterCount']} points regroupés"


def test_index_simplifies_long_trace_at_low_zoom_and_keeps_ends():
    coordinates = [[-5 + position / 100, 45 + position / 1_000] for position in range(300)]
    index = SpatialCatalogIndex("science", [{
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coordinates},
        "properties": {"source": "csr", "name": "Campagne"},
    }])

    result = index.query(Bbox(-10, 40, 10, 55), zoom=2, source="csr")
    rendered = result["features"][0]["geometry"]["coordinates"]

    assert len(rendered) <= 64
    assert rendered[0] == coordinates[0]
    assert rendered[-1] == coordinates[-1]


def test_parse_bbox_rejects_invalid_latitude_but_keeps_wrapped_longitude():
    assert parse_bbox("170,-10,-170,10") == Bbox(170, -10, -170, 10)
    with pytest.raises(ValueError):
        parse_bbox("0,-91,1,1")
