"""Vent de zone — même logique que src/utils/climatologyWind.js. kind: climatology."""
from __future__ import annotations

import math
from typing import Any, Dict


def _interp(v: float, v0: float, v1: float, r0: float, r1: float) -> float:
    if v1 == v0:
        return r0
    t = max(0.0, min(1.0, (v - v0) / (v1 - v0)))
    return r0 + t * (r1 - r0)


def _pack(speed_knots: float, dir_from_deg: float) -> Dict[str, Any]:
    return {
        "speedKnots": float(speed_knots),
        "dirFromDeg": float(dir_from_deg),
        "source": "zone_fallback",
        "kind": "climatology",
    }


def zone_wind_at(lat: float, lon: float, month: int) -> Dict[str, Any]:
    m = max(1, min(12, int(month or 1)))
    if lat > 60:
        return _pack(18 + 4 * math.sin((m * 30 * math.pi) / 180), 240)
    if lat < -60:
        return _pack(28 + 5 * math.sin((m * 30 * math.pi) / 180), 270)

    in_atlantic = -80 <= lon <= 20
    in_indian = 20 <= lon <= 120
    in_pacific = lon >= 120 or lon <= -80
    in_med = -10 <= lon <= 40 and 30 <= lat <= 47

    if in_med:
        if m in (6, 7, 8):
            return _pack(14, 340)
        if m in (12, 1, 2):
            return _pack(16, 220)
        return _pack(10, 300)
    if in_atlantic and 25 <= lat <= 40:
        return _pack(10, 260) if m in (6, 7, 8, 9) else _pack(14, 240)
    if in_atlantic and 5 <= lat <= 25:
        spd = 15
        if m in (12, 1, 2, 3):
            spd = 18
        elif m in (6, 7, 8, 9):
            spd = 12
        return _pack(spd, 50)
    if in_atlantic and -25 <= lat <= 5:
        return _pack(16 if m in (6, 7, 8) else 13, 130)
    if in_atlantic and -50 <= lat <= -25:
        return _pack(20 + 5 * _interp(lat, -25, -50, 0, 1), 270)
    if in_indian and lat >= 5:
        if m in (6, 7, 8, 9):
            return _pack(20, 225)
        if m in (12, 1, 2, 3):
            return _pack(14, 45)
        return _pack(8, 90)
    if in_indian and -25 <= lat <= 5:
        return _pack(17 if m in (6, 7, 8) else 13, 135)
    if in_indian and -60 <= lat <= -25:
        return _pack(22 + 8 * _interp(lat, -25, -60, 0, 1), 270)
    if in_pacific and 5 <= lat <= 25:
        spd = 14
        if m in (12, 1, 2, 3):
            spd = 17
        elif m in (7, 8, 9):
            spd = 12
        return _pack(spd, 55)
    if in_pacific and -30 <= lat <= 5:
        return _pack(16 if m in (6, 7, 8, 9) else 13, 120)
    if in_pacific and 35 <= lat <= 60:
        return _pack(25 if m in (12, 1, 2, 3) else 16, 260)
    if in_pacific and -60 <= lat <= -30:
        return _pack(20 + 7 * _interp(lat, -30, -60, 0, 1), 270)
    if in_atlantic and 40 <= lat <= 60:
        return _pack(22 if m in (12, 1, 2) else 15, 255)
    if abs(lat) <= 8:
        itcz = 5 * math.sin(((m - 7) * 30 * math.pi) / 180)
        if abs(lat - itcz) < 4:
            return _pack(4, 200)
    if -60 <= lat <= -40:
        return _pack(25 + 5 * _interp(lat, -40, -60, 0, 1), 275)
    return _pack(10, 270)


def boat_speed_from_wind(wind_knots: float) -> float:
    """Repli sans polaire. Ne pas appeler si une table polaire est disponible."""
    raw = float(wind_knots) * 0.45
    return round(max(4.0, min(11.0, raw)) * 10) / 10
