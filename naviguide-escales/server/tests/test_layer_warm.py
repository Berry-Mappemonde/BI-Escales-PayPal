"""Cellules AMP le long d'un trait, pas le monde."""
import asyncio

import ici_engine
from ici_engine import (
    accept_layer_warm,
    amp_cells_from_points,
    layer_warm_status,
    reset_caches,
    warm_amp_cells_along,
)


def test_amp_cells_from_points_unique_and_capped():
    reset_caches()
    pts = [
        [46.15, -1.16],
        [46.80, -1.20],  # même cellule 1°
        [41.31, 9.19],
        ["x"],
        [91.0, 0.0],
        None,
    ]
    cells = amp_cells_from_points(pts)
    assert cells == [(46.5, -1.5), (41.5, 9.5)]
    many = [[float(i) + 0.1, 0.1] for i in range(-40, 50)]
    assert len(amp_cells_from_points(many)) == ici_engine.LAYER_WARM_MAX_CELLS
    assert amp_cells_from_points([]) == []


def test_accept_layer_warm_rejects_while_running():
    reset_caches()
    first = accept_layer_warm([[46.15, -1.16]])
    assert first["accepted"] is True
    assert first["status"] == "queued"
    assert first["cellsTotal"] == 1
    second = accept_layer_warm([[41.31, 9.19]])
    assert second["accepted"] is False
    reset_caches()
    assert layer_warm_status()["status"] == "idle"


def test_warm_amp_cells_along_counts_hits(monkeypatch):
    reset_caches()
    seen = []

    async def fake_sig(_client):
        return "1"

    async def fake_cell(_client, lat, lon):
        seen.append((lat, lon))
        return [{"id": f"{lat}:{lon}"}]

    monkeypatch.setattr(ici_engine, "refresh_amp_layer_sig", fake_sig)
    monkeypatch.setattr(ici_engine, "_amp_cell_features", fake_cell)
    monkeypatch.setattr(ici_engine, "LAYER_WARM_PAUSE_S", 0)
    out = asyncio.run(warm_amp_cells_along([[46.15, -1.16], [41.31, 9.19]]))
    assert out["status"] == "done"
    assert out["cellsTotal"] == 2
    assert out["cellsDone"] == 2
    assert out["cellsCached"] == 2
    assert out["errors"] == 0
    assert seen == [(46.5, -1.5), (41.5, 9.5)]


def test_warm_amp_cells_along_counts_errors(monkeypatch):
    reset_caches()

    async def fake_sig(_client):
        return "1"

    async def boom(_client, lat, lon):
        raise RuntimeError("bi")

    monkeypatch.setattr(ici_engine, "refresh_amp_layer_sig", fake_sig)
    monkeypatch.setattr(ici_engine, "_amp_cell_features", boom)
    monkeypatch.setattr(ici_engine, "LAYER_WARM_PAUSE_S", 0)
    out = asyncio.run(warm_amp_cells_along([[46.15, -1.16]]))
    assert out["status"] == "done"
    assert out["errors"] == 1
    assert out["cellsCached"] == 0
    assert out["cellsDone"] == 1


def test_post_layers_warm_kicks_background(monkeypatch):
    from fastapi.testclient import TestClient
    import main

    seen = []

    async def fake(points):
        seen.append(list(points))
        ici_engine._layer_warm.update({
            "status": "done",
            "cellsTotal": 1,
            "cellsDone": 1,
            "cellsCached": 1,
            "errors": 0,
        })
        return ici_engine.layer_warm_status()

    reset_caches()
    monkeypatch.setattr(main, "warm_amp_cells_along", fake)
    client = TestClient(main.app)
    r = client.post("/ici/layers/warm", json={"points": [[46.15, -1.16], [46.2, -1.1]]})
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is True
    assert seen == [[[46.15, -1.16], [46.2, -1.1]]]
    st = client.get("/ici/layers/warm/status")
    assert st.status_code == 200
    assert st.json()["status"] == "done"
    warm = client.get("/ici/warm/status")
    assert warm.status_code == 200
    assert "layers" in warm.json()
