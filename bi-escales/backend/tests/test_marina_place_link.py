"""Google Maps /place/ guard for escale marinas."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bi_marinas_catalog import merge_marina_row
from app.marina_place_link import (
    apply_maps_place_policy,
    evaluate_google_place_link,
    is_google_place_url,
)

BAS_DU_FORT_DRIVING_SCHOOL = (
    "https://www.google.com/maps/place/Auto+%C3%89cole+de+la+Pointe-%C3%A0-Pitre/"
    "@16.2510,-61.5480,17z"
)


def test_bas_du_fort_driving_school_place_rejected():
    marina = {
        "name": "Marina de Bas-du-Fort",
        "lat": 16.2203478,
        "lon": -61.5297219,
        "maps_url": BAS_DU_FORT_DRIVING_SCHOOL,
    }
    ev = evaluate_google_place_link(marina)
    assert ev["safe_place"] is False
    assert ev["rejected_reason"] == "suspicious_name"
    assert "/maps/search/" in (ev["maps_link"] or "")
    assert not is_google_place_url(ev["maps_link"])


def test_merge_applies_place_policy():
    base = {
        "name": "Marina de Bas-du-Fort",
        "lat": 16.2203478,
        "lon": -61.5297219,
        "nm": 1.08,
        "osm_id": "relation/5838544",
    }
    enrich = {"maps_url": BAS_DU_FORT_DRIVING_SCHOOL}
    row = merge_marina_row(base, enrich)
    assert "safe_google_place" not in row
    assert row["maps_url"].startswith("https://www.google.com/maps/search/")


def test_nearby_marina_place_accepted():
    ev = evaluate_google_place_link(
        {
            "name": "Port des Minimes",
            "lat": 46.1467598,
            "lon": -1.1660647,
            "maps_url": "https://www.google.com/maps/place/Port+des+Minimes/@46.1468,-1.1661,17z",
        }
    )
    assert ev["safe_place"] is True


def test_apply_maps_place_policy_sets_flag():
    row = apply_maps_place_policy(
        {
            "name": "Minimes",
            "lat": 46.1467598,
            "lon": -1.1660647,
            "maps_url": "https://www.google.com/maps/place/Port+des+Minimes/@46.1468,-1.1661,17z",
        }
    )
    assert row.get("safe_google_place") is True
