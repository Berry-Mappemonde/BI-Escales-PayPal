from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["service"] == "naviguide-simulator"


def test_polar_chat_is_404():
    r = client.post("/api/v1/polar/chat")
    assert r.status_code == 404


def test_agents_are_404():
    r = client.post("/agents/meteo")
    assert r.status_code == 404


def test_ici_route_exists(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_ICI_WARM", "1")

    async def fake(lat, lon, radius_nm=30, client=None, **_kwargs):
        return {
            "version": 1,
            "at": {"lat": lat, "lon": lon},
            "radiusNm": radius_nm,
            "zee": {"name": "Haute mer", "mrgid": None, "gold": False},
            "poe": [],
            "amp": [],
            "projects": [],
            "nearby": {"marinas": [], "capitaineries": [], "wpi": []},
            "polar": None,
            "event": None,
        }

    monkeypatch.setattr("main.fill_dossier", fake)
    r = client.get("/ici", params={"lat": 46.15, "lon": -1.16})
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 1
    assert body["at"]["lat"] == 46.15
    assert "grid" not in (body.get("polar") or {})


def test_ici_rejects_bad_coords():
    r = client.get("/ici", params={"lat": 120, "lon": 0})
    assert r.status_code == 400
