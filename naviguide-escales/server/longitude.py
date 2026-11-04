"""Longitudes : la seule implémentation côté serveur.

Toute longitude repliée, dépliée, comparée ou interpolée passe par ce module
(même contrat que ``src/utils/geo.js`` côté client). Un repli écrit à la main
ailleurs est refusé par ``tests/test_longitude_guard.py``.

Contrat :
- ``wrap_lon`` ramène dans [-180, 180] ; une valeur déjà dans l'intervalle
  est rendue telle quelle (±180 compris), au bit près.
- ``unwrap_lon(ref, lon)`` choisit la copie de ``lon`` à moins de 180° de
  ``ref`` (polyligne continue au passage de l'antiméridien).
- ``delta_lon(a, b)`` : écart signé le plus court de ``a`` vers ``b``.
- ``interp_lon_shortest(a, b, t)`` : interpolation par le plus court arc,
  résultat replié. -180 puis 179.85 ne traverse pas le globe.
- Valeurs non finies (NaN, inf) : rendues telles quelles, jamais de boucle.
"""

from __future__ import annotations

import math
from typing import Optional

__all__ = [
    "delta_lon",
    "interp_lon_shortest",
    "lon_east_of",
    "unwrap_lon",
    "wrap_lon",
    "wrap_lon_into",
]


def wrap_lon(lon: float) -> float:
    """Longitude ramenée dans [-180, 180]."""
    x = float(lon)
    if not math.isfinite(x) or -180.0 <= x <= 180.0:
        return x
    if abs(x) > 720.0:
        x = math.fmod(x, 360.0)
    while x > 180.0:
        x -= 360.0
    while x < -180.0:
        x += 360.0
    return x


def unwrap_lon(ref: Optional[float], lon: float) -> float:
    """Copie de ``lon`` à moins de 180° de ``ref`` (``ref`` absent : ``lon``)."""
    x = float(lon)
    if ref is None:
        return x
    r = float(ref)
    if not math.isfinite(x) or not math.isfinite(r):
        return x
    if abs(x - r) > 720.0:
        x = r + math.fmod(x - r, 360.0)
    while x - r > 180.0:
        x -= 360.0
    while x - r < -180.0:
        x += 360.0
    return x


def delta_lon(a: float, b: float) -> float:
    """Écart signé le plus court de ``a`` vers ``b``, dans [-180, 180]."""
    return wrap_lon(float(b) - float(a))


def interp_lon_shortest(a: float, b: float, t: float) -> float:
    """Interpolation par le plus court arc (t = 0 → a, t = 1 → b), repliée."""
    return wrap_lon(float(a) + delta_lon(a, b) * float(t))


def wrap_lon_into(lon: float, west: float) -> float:
    """Longitude ramenée dans [west, west + 360) (grilles 0–360, HYCOM…)."""
    x = float(lon)
    w = float(west)
    if not math.isfinite(x) or not math.isfinite(w):
        return x
    if abs(x - w) > 720.0:
        x = w + math.fmod(x - w, 360.0)
    while x < w:
        x += 360.0
    while x >= w + 360.0:
        x -= 360.0
    return x


def lon_east_of(lon: float, west: float) -> float:
    """``wrap_lon(lon)`` décalé de +360° tant qu'il est à l'ouest de ``west``."""
    x = wrap_lon(lon)
    w = float(west)
    if not math.isfinite(x) or not math.isfinite(w):
        return x
    while x < w:
        x += 360.0
    return x
