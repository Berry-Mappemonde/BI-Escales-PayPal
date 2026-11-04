"""Garde-fou : aucun repli de longitude écrit à la main hors de longitude.py.

L'antiméridien a été corrigé plusieurs fois parce que le calcul existait en
plusieurs copies : chaque correctif en réparait une, une autre restait fausse.
Ce test échoue si une nouvelle boucle ``-= 360`` / ``+= 360`` ou un repli
``(x + 180) % 360 - 180`` apparaît dans le serveur ou les scripts. Utilisez
``wrap_lon``, ``unwrap_lon``, ``delta_lon`` ou ``interp_lon_shortest``.

Seules exceptions : les directions (vent, courant), qui ne sont pas des
longitudes. Elles sont listées ici une par une, au mot près.
"""
from __future__ import annotations

import re
from pathlib import Path

SIM = Path(__file__).resolve().parents[2]
ROOTS = (SIM / "server", SIM / "scripts")
HELPER = SIM / "server" / "longitude.py"

AD_HOC = (
    re.compile(r"[-+]=\s*360(\.0*)?\b"),
    re.compile(r"[+-]\s*(180|540)(\.0*)?\s*\)\s*%\s*360"),
)

# (fichier relatif à naviguide-simulator, ligne sans espaces de bord) : directions.
ALLOWED = {
    ("server/hindcast.py", "s = sum(abs(((x - cand + 180.0) % 360.0) - 180.0) for x in degs)"),
    ("server/hindcast.py", "arcs = [abs(((x - y + 180.0) % 360.0) - 180.0) for x in nums for y in nums]"),
    ("server/forecast_blend.py", "d = (b - a + 540) % 360 - 180"),
}


def _sources():
    for root in ROOTS:
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(SIM).as_posix()
            if path == HELPER or "/tests/" in f"/{rel}" or "__pycache__" in rel:
                continue
            yield rel, path


def _code(line: str) -> str:
    return line.split("#", 1)[0].strip()


def test_no_ad_hoc_longitude_wrap_outside_helper():
    offenders = []
    for rel, path in _sources():
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = _code(line)
            if not code or not any(p.search(code) for p in AD_HOC):
                continue
            if (rel, code) in ALLOWED:
                continue
            offenders.append(f"{rel}:{no}: {code}")
    assert not offenders, (
        "Repli de longitude écrit à la main ; passez par server/longitude.py :\n"
        + "\n".join(offenders)
    )


def test_allowed_exceptions_still_exist():
    """Une exception devenue inutile doit sortir de la liste."""
    present = set()
    for rel, path in _sources():
        for line in path.read_text(encoding="utf-8").splitlines():
            present.add((rel, _code(line)))
    assert ALLOWED <= present, sorted(ALLOWED - present)


def test_guard_catches_known_patterns():
    samples = (
        "while x > 180: x -= 360",
        "lon += 360.0",
        "return ((lon + 180.0) % 360.0) - 180.0",
        "lon2 = (math.degrees(lam2) + 540) % 360 - 180",
    )
    for s in samples:
        assert any(p.search(s) for p in AD_HOC), s
    for s in ("h = ((heading % 360) + 360) % 360", "return 360 - raw if raw > 180 else raw"):
        assert not any(p.search(s) for p in AD_HOC), s
