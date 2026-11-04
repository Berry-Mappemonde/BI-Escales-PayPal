"""Table de piraterie : Aden HIGH, Atlantique nord rien, R10a daté."""

from piracy import attach_piracy, zone_at


ADEN = (12.6, 48.2)
NORTH_ATLANTIC = (45.0, -30.0)
LA_ROCHELLE = (46.15, -1.17)


def test_aden_is_high():
    zone = zone_at(*ADEN)
    assert zone is not None
    assert zone["name"] == "Horn of Africa / Gulf Aden"
    assert zone["level"] == "HIGH"
    assert zone["source"] == "IMB/UKMTO"
    assert "score" not in zone


def test_north_atlantic_is_nothing():
    assert zone_at(*NORTH_ATLANTIC) is None
    assert zone_at(*LA_ROCHELLE) is None


def test_overlap_picks_aden_over_somalia():
    zone = zone_at(12.5, 50.0)
    assert zone is not None
    assert zone["name"] == "Horn of Africa / Gulf Aden"
    assert zone["level"] == "HIGH"


def test_malacca_is_medium():
    zone = zone_at(3.0, 101.0)
    assert zone is not None
    assert zone["level"] == "MEDIUM"
    assert zone["name"] == "Strait of Malacca"


def test_attach_piracy_on_bag():
    aden = {"at": {"lat": ADEN[0], "lon": ADEN[1]}, "zee": None}
    attach_piracy(aden)
    assert aden["piracy"]["level"] == "HIGH"
    assert aden["piracy"]["name"] == "Horn of Africa / Gulf Aden"
    quiet = {"at": {"lat": LA_ROCHELLE[0], "lon": LA_ROCHELLE[1]}}
    attach_piracy(quiet)
    assert quiet["piracy"] is None


def test_r10a_aden_is_a_dated_piracy_alert():
    from plan_alerts import clear_plan_cache, evaluate_plan

    clear_plan_cache()
    plan = {
        "legs": [{
            "from": "Aden",
            "to": "Aden",
            "depart": "2026-10-01",
            "kn": 8.0,
            "holdDays": 0,
            "points": [
                {"lat": ADEN[0], "lon": ADEN[1]},
                {"lat": 12.7, "lon": 48.5},
            ],
        }],
        "skipper_thresholds": {"galeKt": 99, "hsAlertM": 99},
    }
    out = evaluate_plan(plan, now="2026-09-22T12:00:00Z")
    piracy = [a for leg in out["legs"] for a in leg["alerts"] if a["kind"] == "piracy"]
    assert piracy, out
    alert = piracy[0]
    assert alert["weight"] == 3
    assert alert["severity"] == "alert"
    assert "Horn of Africa / Gulf Aden" in alert["fact"]
    assert "HIGH" in alert["fact"]
    assert "IMB/UKMTO" in alert["fact"]
    assert alert["when"] and len(str(alert["when"])) >= 10

    clear_plan_cache()
    quiet = {
        "legs": [{
            "from": "Atlantic",
            "to": "Atlantic",
            "depart": "2026-10-01",
            "kn": 8.0,
            "holdDays": 0,
            "points": [
                {"lat": NORTH_ATLANTIC[0], "lon": NORTH_ATLANTIC[1]},
                {"lat": 46.0, "lon": -28.0},
            ],
        }],
        "skipper_thresholds": {"galeKt": 99, "hsAlertM": 99},
    }
    silent = evaluate_plan(quiet, now="2026-09-22T12:00:00Z")
    kinds = {a["kind"] for leg in silent["legs"] for a in leg["alerts"]}
    assert "piracy" not in kinds
