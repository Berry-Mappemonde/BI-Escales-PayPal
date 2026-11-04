"""Unit tests for climatology_zones.py"""
import math
import pytest
from climatology_zones import zone_wind_at, boat_speed_from_wind


class TestZoneWindAt:
    def test_polar_north_gt_60(self):
        lat = 65.0
        lon = 0.0
        month = 6
        result = zone_wind_at(lat, lon, month)
        expected_speed = 18 + 4 * math.sin((month * 30 * math.pi) / 180)
        expected = {
            "speedKnots": float(expected_speed),
            "dirFromDeg": 240.0,
            "source": "zone_fallback",
            "kind": "climatology",
        }
        assert result == expected
        assert set(result.keys()) == {"speedKnots", "dirFromDeg", "source", "kind"}
        assert result["source"] == "zone_fallback"
        assert result["kind"] == "climatology"

    def test_polar_south_lt_minus_60(self):
        lat = -65.0
        lon = 0.0
        month = 12
        result = zone_wind_at(lat, lon, month)
        expected_speed = 28 + 5 * math.sin((month * 30 * math.pi) / 180)
        expected = {
            "speedKnots": float(expected_speed),
            "dirFromDeg": 270.0,
            "source": "zone_fallback",
            "kind": "climatology",
        }
        assert result == expected
        assert set(result.keys()) == {"speedKnots", "dirFromDeg", "source", "kind"}

    def test_mediterranean_summer(self):
        lat = 40.0
        lon = 10.0
        for m in (6, 7, 8):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 14.0,
                "dirFromDeg": 340.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_mediterranean_winter(self):
        lat = 40.0
        lon = 10.0
        for m in (12, 1, 2):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 16.0,
                "dirFromDeg": 220.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_mediterranean_shoulder(self):
        lat = 40.0
        lon = 10.0
        for m in (3, 4, 5, 9, 10, 11):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 10.0,
                "dirFromDeg": 300.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_atlantic_trades_north_summer(self):
        lat = 30.0
        lon = -30.0
        for m in (6, 7, 8, 9):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 10.0,
                "dirFromDeg": 260.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_atlantic_trades_north_winter(self):
        lat = 30.0
        lon = -30.0
        for m in (10, 11, 12, 1, 2, 3, 4, 5):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 14.0,
                "dirFromDeg": 240.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_atlantic_trades_tropics_winter(self):
        lat = 15.0
        lon = -30.0
        for m in (12, 1, 2, 3):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 18.0,
                "dirFromDeg": 50.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_atlantic_trades_tropics_summer(self):
        lat = 15.0
        lon = -30.0
        for m in (6, 7, 8, 9):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 12.0,
                "dirFromDeg": 50.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_atlantic_trades_tropics_shoulder(self):
        lat = 15.0
        lon = -30.0
        for m in (4, 5, 10, 11):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 15.0,
                "dirFromDeg": 50.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_atlantic_equatorial_summer(self):
        lat = 0.0
        lon = -30.0
        for m in (6, 7, 8):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 16.0,
                "dirFromDeg": 130.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_atlantic_equatorial_other(self):
        lat = 0.0
        lon = -30.0
        for m in (1, 2, 3, 4, 5, 9, 10, 11, 12):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 13.0,
                "dirFromDeg": 130.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_atlantic_south_interpolation(self):
        lat = -37.5
        lon = -30.0
        month = 1
        result = zone_wind_at(lat, lon, month)
        t = (lat - (-25)) / (-50 - (-25))
        t = max(0.0, min(1.0, t))
        expected_speed = 20 + 5 * t
        expected = {
            "speedKnots": float(expected_speed),
            "dirFromDeg": 270.0,
            "source": "zone_fallback",
            "kind": "climatology",
        }
        assert result == expected

    def test_indian_monsoon_summer(self):
        lat = 10.0
        lon = 60.0
        for m in (6, 7, 8, 9):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 20.0,
                "dirFromDeg": 225.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_indian_monsoon_winter(self):
        lat = 10.0
        lon = 60.0
        for m in (12, 1, 2, 3):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 14.0,
                "dirFromDeg": 45.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_indian_monsoon_shoulder(self):
        lat = 10.0
        lon = 60.0
        for m in (4, 5, 10, 11):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 8.0,
                "dirFromDeg": 90.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_indian_equatorial_summer(self):
        lat = 0.0
        lon = 60.0
        for m in (6, 7, 8):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 17.0,
                "dirFromDeg": 135.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_indian_equatorial_other(self):
        lat = 0.0
        lon = 60.0
        for m in (1, 2, 3, 4, 5, 9, 10, 11, 12):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 13.0,
                "dirFromDeg": 135.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_indian_south_interpolation(self):
        lat = -42.5
        lon = 60.0
        month = 1
        result = zone_wind_at(lat, lon, month)
        t = (lat - (-25)) / (-60 - (-25))
        t = max(0.0, min(1.0, t))
        expected_speed = 22 + 8 * t
        expected = {
            "speedKnots": float(expected_speed),
            "dirFromDeg": 270.0,
            "source": "zone_fallback",
            "kind": "climatology",
        }
        assert result == expected

    def test_pacific_tropics_winter(self):
        lat = 15.0
        lon = 150.0
        for m in (12, 1, 2, 3):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 17.0,
                "dirFromDeg": 55.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_pacific_tropics_summer(self):
        lat = 15.0
        lon = 150.0
        for m in (7, 8, 9):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 12.0,
                "dirFromDeg": 55.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_pacific_tropics_shoulder(self):
        lat = 15.0
        lon = 150.0
        for m in (4, 5, 6, 10, 11):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 14.0,
                "dirFromDeg": 55.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_pacific_equatorial_summer(self):
        lat = 0.0
        lon = 150.0
        for m in (6, 7, 8, 9):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 16.0,
                "dirFromDeg": 120.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_pacific_equatorial_other(self):
        lat = 0.0
        lon = 150.0
        for m in (1, 2, 3, 4, 5, 10, 11, 12):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 13.0,
                "dirFromDeg": 120.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_pacific_north_winter(self):
        lat = 50.0
        lon = 150.0
        for m in (12, 1, 2, 3):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 25.0,
                "dirFromDeg": 260.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_pacific_north_other(self):
        lat = 50.0
        lon = 150.0
        for m in (4, 5, 6, 7, 8, 9, 10, 11):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 16.0,
                "dirFromDeg": 260.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_pacific_south_interpolation(self):
        lat = -45.0
        lon = 150.0
        month = 1
        result = zone_wind_at(lat, lon, month)
        t = (lat - (-30)) / (-60 - (-30))
        t = max(0.0, min(1.0, t))
        expected_speed = 20 + 7 * t
        expected = {
            "speedKnots": float(expected_speed),
            "dirFromDeg": 270.0,
            "source": "zone_fallback",
            "kind": "climatology",
        }
        assert result == expected

    def test_atlantic_high_lat_winter(self):
        lat = 50.0
        lon = -30.0
        for m in (12, 1, 2):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 22.0,
                "dirFromDeg": 255.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_atlantic_high_lat_other(self):
        lat = 50.0
        lon = -30.0
        for m in (3, 4, 5, 6, 7, 8, 9, 10, 11):
            result = zone_wind_at(lat, lon, m)
            expected = {
                "speedKnots": 15.0,
                "dirFromDeg": 255.0,
                "source": "zone_fallback",
                "kind": "climatology",
            }
            assert result == expected

    def test_itcz_zone_unreachable_due_to_atlantic_band(self):
        # ITCZ check is after Atlantic equatorial band, so this point hits Atlantic instead
        lat = 2.0
        lon = 0.0
        month = 7
        result = zone_wind_at(lat, lon, month)
        expected = {
            "speedKnots": 16.0,
            "dirFromDeg": 130.0,
            "source": "zone_fallback",
            "kind": "climatology",
        }
        assert result == expected

    def test_southern_ocean_interpolation_atlantic_gap(self):
        # Southern Ocean check at -60 <= lat <= -40 is reached for Atlantic lon
        # when lat is in [-60, -50) because Atlantic band only covers [-50, -25]
        lat = -55.0
        lon = 0.0
        month = 1
        result = zone_wind_at(lat, lon, month)
        t = (lat - (-40)) / (-60 - (-40))
        t = max(0.0, min(1.0, t))
        expected_speed = 25 + 5 * t
        expected = {
            "speedKnots": float(expected_speed),
            "dirFromDeg": 275.0,
            "source": "zone_fallback",
            "kind": "climatology",
        }
        assert result == expected

    def test_default_fallback_pacific_gap(self):
        # Fallback is reached for Pacific latitudes 25-35 (not covered by Pacific bands)
        lat = 30.0
        lon = 150.0
        month = 1
        result = zone_wind_at(lat, lon, month)
        expected = {
            "speedKnots": 10.0,
            "dirFromDeg": 270.0,
            "source": "zone_fallback",
            "kind": "climatology",
        }
        assert result == expected

    def test_month_clamping_zero(self):
        lat = 10.0
        lon = -30.0
        result = zone_wind_at(lat, lon, 0)
        expected = zone_wind_at(lat, lon, 1)
        assert result == expected

    def test_month_clamping_13(self):
        lat = 10.0
        lon = -30.0
        result = zone_wind_at(lat, lon, 13)
        expected = zone_wind_at(lat, lon, 12)
        assert result == expected

    def test_month_none(self):
        lat = 10.0
        lon = -30.0
        result = zone_wind_at(lat, lon, None)
        expected = zone_wind_at(lat, lon, 1)
        assert result == expected

    def test_returned_keys_and_values(self):
        result = zone_wind_at(10.0, -30.0, 6)
        assert set(result.keys()) == {"speedKnots", "dirFromDeg", "source", "kind"}
        assert result["source"] == "zone_fallback"
        assert result["kind"] == "climatology"
        assert isinstance(result["speedKnots"], float)
        assert isinstance(result["dirFromDeg"], float)


class TestBoatSpeedFromWind:
    def test_clamping_min_4(self):
        result = boat_speed_from_wind(5.0)
        assert result == 4.0

    def test_clamping_max_11(self):
        result = boat_speed_from_wind(30.0)
        assert result == 11.0

    def test_rounding_one_decimal(self):
        result = boat_speed_from_wind(10.0)
        assert result == 4.5

    def test_exact_boundary_4(self):
        result = boat_speed_from_wind(8.888888888888889)
        assert result == 4.0

    def test_exact_boundary_11(self):
        result = boat_speed_from_wind(24.444444444444443)
        assert result == 11.0

    def test_mid_range(self):
        result = boat_speed_from_wind(15.0)
        assert result == 6.8

    def test_float_input(self):
        result = boat_speed_from_wind(12.5)
        assert result == 5.6