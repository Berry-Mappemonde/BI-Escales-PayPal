"""Le fichier Berry tient le contrat des passages, sans appeler le moteur.

Cayenne → Papeete passe par Panama et ne descend pas sous 40° S.
Aucun sommet n'entre dans Suez. Le cap de Bonne-Espérance est nommé.
Halifax ↔ Saint-Pierre sont deux features maritimes ; Cayenne ↔ Halifax
n'existe pas. La seule terre est Saint-Maur → La Rochelle. Wallis → Nouméa
reste en deux features. Trente-cinq features maritimes, comme le test de terre.
"""
import json
from pathlib import Path

from route_contract import (
    PANAMA_BOX,
    SUEZ_BOX,
    in_passage_box,
    iter_vertices,
    line_strings,
)

ROUTE = Path(__file__).resolve().parents[2] / "public" / "route.geojson"
FC = json.loads(ROUTE.read_text())
LINES = line_strings(FC)


def test_passage_boxes_match_the_archived_straits():
    assert PANAMA_BOX == (-81.0, 8.5, -79.0, 9.7)
    assert SUEZ_BOX == (32.0, 29.7, 32.7, 31.5)


def test_cayenne_papeete_crosses_panama_and_stays_north_of_40s():
    legs = [
        line
        for line in LINES
        if "Cayenne" in line["from"] and "Papeete" in line["to"]
    ]
    assert legs, "Cayenne → Papeete absent"
    in_panama = []
    for line in legs:
        for lon, lat in (_pair(c) for c in line["coordinates"]):
            assert lat >= -40.0, (lon, lat)
            if in_passage_box(lon, lat, PANAMA_BOX):
                in_panama.append((lon, lat))
    assert in_panama, "aucun sommet de Cayenne → Papeete dans la boîte Panama"


def test_no_vertex_in_the_suez_box():
    hits = [
        (lon, lat)
        for lon, lat in iter_vertices(FC)
        if in_passage_box(lon, lat, SUEZ_BOX)
    ]
    assert hits == []


def test_cape_of_good_hope_is_named():
    named = []
    for feature in FC["features"]:
        props = feature.get("properties") or {}
        blob = " ".join(str(props.get(key) or "") for key in ("name", "from", "to"))
        if "Bonne Espérance" in blob:
            named.append(blob)
    assert named, "aucune feature ne nomme Bonne Espérance"


def test_halifax_saint_pierre_are_two_maritime_directions():
    to_spm = _maritime_legs("Halifax", "Saint-Pierre")
    to_halifax = _maritime_legs("Saint-Pierre", "Halifax")
    assert len(to_spm) == 1
    assert len(to_halifax) == 1


def test_no_feature_joins_cayenne_and_halifax():
    joined = []
    for feature in FC["features"]:
        props = feature.get("properties") or {}
        src = props.get("from") or ""
        dst = props.get("to") or ""
        if ("Cayenne" in src and "Halifax" in dst) or ("Halifax" in src and "Cayenne" in dst):
            joined.append((src, dst))
    assert joined == []


def test_only_overland_is_saint_maur_to_la_rochelle():
    overland = [
        feature
        for feature in FC["features"]
        if (feature.get("properties") or {}).get("type") == "overland"
    ]
    assert len(overland) == 1
    props = overland[0].get("properties") or {}
    geom = overland[0].get("geometry") or {}
    assert str(props.get("from") or "").startswith("Saint-Maur")
    assert props.get("to") == "La Rochelle"
    assert geom.get("type") == "LineString"
    assert len(geom.get("coordinates") or []) == 2


def test_wallis_to_noumea_is_two_features():
    wallis = [
        feature
        for feature in FC["features"]
        if "Wallis" in ((feature.get("properties") or {}).get("from") or "")
        and "Nouméa" in ((feature.get("properties") or {}).get("to") or "")
    ]
    assert len(wallis) == 2


def test_thirty_five_maritime_features():
    maritime = [line for line in LINES if line["type"] == "maritime"]
    assert len(maritime) == 35


def _maritime_legs(src: str, dst: str) -> list[dict]:
    return [
        line
        for line in LINES
        if line["type"] == "maritime" and src in line["from"] and dst in line["to"]
    ]


def _pair(coord) -> tuple[float, float]:
    return float(coord[0]), float(coord[1])
