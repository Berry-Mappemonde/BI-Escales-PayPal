import io
import json

from fastapi import UploadFile

import polar_api


def test_builtin_default_polar_serves_client_payload_without_disk_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(polar_api, "POLAR_DATA_DIR", tmp_path)
    polar_api._default_polar.cache_clear()

    payload = polar_api.get_polar_client(polar_api.DEFAULT_POLAR_EXPEDITION)

    assert payload["boat_name"] == "Leopard 46"
    assert payload["raw"]["twa_rows"] == [0, 30, 35, 40, 45, 50, 52, 60, 75, 90, 92, 102, 110, 111, 113, 115, 120, 135, 150, 152, 160, 161, 170, 180]
    assert "grid" not in payload
    assert not list(tmp_path.iterdir())


def test_upload_stores_client_data_without_generating_full_grid(tmp_path, monkeypatch):
    monkeypatch.setattr(polar_api, "POLAR_DATA_DIR", tmp_path)
    monkeypatch.setattr(
        polar_api.PolarData,
        "generate_full_grid",
        lambda _: (_ for _ in ()).throw(AssertionError("upload must not build the full grid")),
    )
    upload = UploadFile(
        file=io.BytesIO(polar_api.DEFAULT_POLAR_FILE.read_bytes()),
        filename="Leopard46_Standard_Sails.csv",
    )

    result = __import__("asyncio").run(
        polar_api.upload_polar(
            file=upload,
            expedition_id="manual-import",
            boat_name="Manual import",
        )
    )

    stored = json.loads(polar_api._polar_path("manual-import").read_text(encoding="utf-8"))
    assert result["boat_name"] == "Manual import"
    assert "grid" not in result
    assert "grid" not in stored
    assert result["raw"]["twa_rows"][0] == 0


def test_client_polar_payload_reuses_stored_raw_without_grid(tmp_path, monkeypatch):
    monkeypatch.setattr(polar_api, "POLAR_DATA_DIR", tmp_path)
    path = polar_api._polar_path("berry-mappemonde-2026")
    path.write_text(json.dumps({
        "expedition_id": "berry-mappemonde-2026",
        "boat_name": "Leopard 46",
        "created_at": "2026-09-16T00:00:00Z",
        "grid_shape": [181, 61],
        "raw": {"twa_rows": [0, 180], "tws_cols": [6], "matrix": [[0], [8]]},
        "grid": [[0] * 61] * 181,
        "vmg_summary": {"6": {"upwind": {}, "downwind": {}, "gybe_angle": 120}},
    }), encoding="utf-8")

    payload = polar_api.get_polar_client("berry-mappemonde-2026")

    assert payload["raw"]["twa_rows"] == [0, 180]
    assert payload["vmg_summary"]["6"]["gybe_angle"] == 120
    assert "grid" not in payload


def test_corrupt_polar_file_falls_back_to_default(tmp_path, monkeypatch):
    """JSON corrompu → 200 avec la polaire par défaut, pas un 500."""
    monkeypatch.setattr(polar_api, "POLAR_DATA_DIR", tmp_path)
    polar_api._default_polar.cache_clear()
    dest = polar_api._polar_path(polar_api.DEFAULT_POLAR_EXPEDITION)
    dest.write_text("{not json", encoding="utf-8")

    payload = polar_api.get_polar_client(polar_api.DEFAULT_POLAR_EXPEDITION)

    assert payload["boat_name"] == "Leopard 46"
    assert payload["raw"]["twa_rows"][0] == 0
    assert payload.get("source") == "default"


def test_old_polar_format_without_raw_falls_back_to_default(tmp_path, monkeypatch):
    """Format ancien (pas de raw) → repli défaut, pas KeyError."""
    monkeypatch.setattr(polar_api, "POLAR_DATA_DIR", tmp_path)
    polar_api._default_polar.cache_clear()
    dest = polar_api._polar_path(polar_api.DEFAULT_POLAR_EXPEDITION)
    dest.write_text(json.dumps({
        "expedition_id": "berry-mappemonde-2026",
        "boat_name": "Ancien format",
        "grid": [[0]],
    }), encoding="utf-8")

    payload = polar_api.get_polar_client(polar_api.DEFAULT_POLAR_EXPEDITION)

    assert payload["boat_name"] == "Leopard 46"
    assert "raw" in payload
    assert payload.get("source") == "default"
