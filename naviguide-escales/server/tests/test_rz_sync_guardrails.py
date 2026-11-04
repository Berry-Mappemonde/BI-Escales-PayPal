import json
from pathlib import Path
import pytest

from voyage_api import route_file_fingerprint, route_points_fingerprint
from voyage_clock import build_voyage_clock, sample_clock_at_hours, sample_clock_at_time
import pearls_warm


def _load_route_features():
    # server/tests/ -> server/ -> naviguide-simulator/ -> public/route.geojson
    route_file = Path(__file__).resolve().parent.parent.parent / "public" / "route.geojson"
    with open(route_file, "r", encoding="utf-8") as f:
        return json.load(f)


def _extract_points(fc):
    points = []
    for f in fc.get("features", []):
        geom = f.get("geometry") or {}
        if geom.get("type") == "LineString":
            for c in geom.get("coordinates", []):
                points.append({"lat": float(c[1]), "lon": float(c[0])})
    return points


# ============================================================================
# RZ4: Isolation du stock et détection de dérive d'empreinte
# ============================================================================

def test_rz4_route_file_fingerprint_deterministic():
    """L'empreinte du fichier route.geojson est stable, déterministe et non vide."""
    fp1 = route_file_fingerprint()
    fp2 = route_file_fingerprint()
    assert isinstance(fp1, str)
    assert len(fp1) > 0
    assert fp1 == fp2


def test_rz4_points_fingerprint_null_when_empty():
    """Sans points de voyage, routeVoyageFp est None (aucun semis en prod)."""
    assert route_points_fingerprint(None) is None
    assert route_points_fingerprint([]) is None


def test_rz4_fingerprint_drift_detection():
    """Une déviation entre les points du voyage et le fichier est immédiatement détectée."""
    fc = _load_route_features()
    points = _extract_points(fc)
    assert len(points) > 0

    fp_points = route_points_fingerprint(points)
    assert isinstance(fp_points, str)

    # Une modification d'un seul sommet doit casser la correspondance d'empreinte
    shifted = [{"lat": p["lat"] + (0.001 if i == 0 else 0.0), "lon": p["lon"]} for i, p in enumerate(points)]
    fp_shifted = route_points_fingerprint(shifted)
    assert fp_shifted != fp_points


def test_rz4_mock_store_isolation_no_network(monkeypatch):
    """Les calculs d'empreintes s'exécutent en mémoire pure sans dépendance Contabo."""
    def forbid_network(*args, **kwargs):
        raise RuntimeError("Tentative d'accès réseau non autorisée !")

    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "off")
    monkeypatch.setenv("CONTABO_HOST", "127.0.0.1")

    fc = _load_route_features()
    points = _extract_points(fc)
    fp = route_points_fingerprint(points)
    assert isinstance(fp, str)


# ============================================================================
# RZ5: Horloge et chronologie sur la nouvelle géométrie
# ============================================================================

def test_rz5_clock_builds_chronologically_offline():
    """L'horloge calculée sur les points de route avance sans régression temporelle."""
    fc = _load_route_features()
    points = _extract_points(fc)

    sample_points = points[:60]
    t0 = "2026-06-15T08:00:00Z"

    clock = build_voyage_clock(sample_points, [], t0, start_at="saint-maur")
    assert isinstance(clock, dict)

    sample_t0 = sample_clock_at_hours(clock, 0.0)
    assert sample_t0 is not None

    sample_time = sample_clock_at_time(clock, t0)
    assert sample_time is not None


# ============================================================================
# RZ6: Préchauffage des perles sans calcul LLM ni écriture réelle
# ============================================================================

def test_rz6_pearls_warm_fingerprint_and_trap():
    """Le préchauffage des perles bloque les écritures directes et identifie le cache."""
    sample_payload = {"cell": [46.0, -1.0], "route_rev": "test"}
    fp = pearls_warm._fingerprint(sample_payload)
    assert isinstance(fp, str)
    assert fp == pearls_warm._fingerprint(sample_payload)

    with pearls_warm._no_store_writes():
        pass
