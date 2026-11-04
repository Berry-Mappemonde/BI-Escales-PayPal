"""Polar upload / lecture — sans chat. Extrait de polar_api/main.py."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi.concurrency import run_in_threadpool
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from admin_guard import require_admin
from polar_engine import PolarData, parse_polar_csv, parse_polar_excel, parse_polar_pdf

POLAR_DATA_DIR = Path(os.environ.get(
    "NAVIGUIDE_POLAR_DIR",
    str(Path(__file__).resolve().parent / "polar_data"),
))
POLAR_DATA_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_POLAR_EXPEDITION = "berry-mappemonde-2026"
DEFAULT_POLAR_NAME = "Leopard 46"
DEFAULT_POLAR_FILE = Path(__file__).resolve().parents[1] / "public" / "Leopard46_Standard_Sails.csv"
MAX_POLAR_UPLOAD_BYTES = 10 * 1024 * 1024

log = logging.getLogger("naviguide-simulator.polar")
router = APIRouter()


def _polar_path(expedition_id: str) -> Path:
    safe = expedition_id.replace("/", "_").replace("\\", "_").replace(" ", "_")
    return POLAR_DATA_DIR / f"polar_{safe}.json"


def _read_stored_polar(expedition_id: str) -> Optional[Dict[str, Any]]:
    dest = _polar_path(expedition_id)
    if not dest.exists():
        return None
    try:
        with open(dest, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        log.warning("polaire stockée illisible %s: %s — repli défaut", dest.name, exc)
        return None
    if not isinstance(data, dict):
        log.warning("polaire stockée invalide %s: pas un objet — repli défaut", dest.name)
        return None
    return data


@lru_cache(maxsize=1)
def _default_polar() -> PolarData:
    """Charge une polaire de secours livrée avec le simulateur, sans upload HTTP."""
    try:
        return parse_polar_csv(DEFAULT_POLAR_FILE.read_bytes(), boat_name=DEFAULT_POLAR_NAME)
    except Exception as exc:
        log.exception("Default polar loading failed")
        raise HTTPException(
            status_code=503,
            detail="La polaire par défaut est indisponible.",
        ) from exc


def _serialize_polar(polar: PolarData, expedition_id: str) -> Dict[str, Any]:
    vmg_summary = polar.summary()
    return {
        "expedition_id": expedition_id,
        "boat_name": polar.boat_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "grid_shape": [181, 61],
        "raw": {
            "twa_rows": polar.twa_rows,
            "tws_cols": polar.tws_cols,
            "matrix": polar.matrix.tolist(),
        },
        "vmg_summary": {
            str(tws): {
                "upwind": d["upwind"],
                "downwind": d["downwind"],
                "gybe_angle": d["gybe_angle"],
            }
            for tws, d in vmg_summary.items()
        },
    }


def _polar_from_stored(data: Dict[str, Any]) -> PolarData:
    raw = data.get("raw")
    if not isinstance(raw, dict):
        raise ValueError("format ancien: champ raw absent")
    twa, tws, matrix = raw.get("twa_rows"), raw.get("tws_cols"), raw.get("matrix")
    if not twa or not tws or matrix is None:
        raise ValueError("format ancien: raw incomplet")
    return PolarData(
        twa,
        tws,
        matrix,
        boat_name=data.get("boat_name", "Boat"),
    )


def _fallback_default_polar(expedition_id: str, why: str) -> tuple[Dict[str, Any], PolarData]:
    log.warning("polaire %s: %s — repli sur la polaire par défaut", expedition_id, why)
    polar = _default_polar()
    payload = _serialize_polar(polar, expedition_id)
    payload["source"] = "default"
    return payload, polar


def _stored_or_default_polar(expedition_id: str) -> tuple[Dict[str, Any], PolarData]:
    dest = _polar_path(expedition_id)
    data = _read_stored_polar(expedition_id)
    if data is not None:
        try:
            return data, _polar_from_stored(data)
        except Exception as exc:
            return _fallback_default_polar(expedition_id, f"{type(exc).__name__}: {exc}")
    if dest.exists():
        return _fallback_default_polar(expedition_id, "fichier illisible")
    if expedition_id == DEFAULT_POLAR_EXPEDITION:
        polar = _default_polar()
        return _serialize_polar(polar, expedition_id), polar
    raise HTTPException(
        status_code=404,
        detail=f"No polar data found for expedition '{expedition_id}'.",
    )


def _load_polar_data(expedition_id: str) -> PolarData:
    _, polar = _stored_or_default_polar(expedition_id)
    return polar


def _parse_uploaded_polar(raw_bytes: bytes, filename: str, boat_name: str) -> PolarData:
    if filename.endswith(".pdf"):
        return parse_polar_pdf(raw_bytes, boat_name=boat_name)
    if filename.endswith(".csv"):
        return parse_polar_csv(raw_bytes, boat_name=boat_name)
    return parse_polar_excel(raw_bytes, boat_name=boat_name)


def _write_polar_data(dest: Path, data: Dict[str, Any]) -> None:
    """Écrit atomiquement pour qu'un import interrompu ne corrompe pas le cache."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=dest.parent,
            prefix=f".{dest.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp:
            temp_name = temp.name
            json.dump(data, temp, ensure_ascii=False, separators=(",", ":"))
        os.replace(temp_name, dest)
    except OSError:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)
        raise


# Sécurité P0 : parser un PDF / XLSX inconnu et écrire sur disque = admin seulement.
@router.post("/api/v1/polar/upload", dependencies=[Depends(require_admin)])
async def upload_polar(
    file: UploadFile = File(...),
    expedition_id: str = Form(...),
    boat_name: Optional[str] = Form(None),
):
    fname = (file.filename or "").lower()
    allowed = (".pdf", ".csv", ".xlsx", ".xls")
    if not any(fname.endswith(ext) for ext in allowed):
        raise HTTPException(status_code=400, detail="Accepted formats: PDF, CSV, XLSX, XLS.")

    bname = boat_name or expedition_id
    raw_bytes = await file.read(MAX_POLAR_UPLOAD_BYTES + 1)
    if len(raw_bytes) > MAX_POLAR_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Le fichier polaire dépasse la taille maximale de 10 Mo.",
        )
    if not raw_bytes:
        raise HTTPException(status_code=422, detail="Le fichier polaire est vide.")

    try:
        polar = await run_in_threadpool(_parse_uploaded_polar, raw_bytes, fname, bname)
    except Exception as exc:
        log.error("File parsing failed: %s", exc)
        raise HTTPException(status_code=422, detail=f"Parsing error: {exc}") from exc

    try:
        data = await run_in_threadpool(_serialize_polar, polar, expedition_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Polar serialization error: {exc}") from exc

    dest = _polar_path(expedition_id)
    try:
        await run_in_threadpool(_write_polar_data, dest, data)
    except OSError as exc:
        log.exception("Polar data could not be saved")
        raise HTTPException(status_code=500, detail="Impossible d'enregistrer la polaire.") from exc

    return {
        "status": "ok",
        "expedition_id": expedition_id,
        "boat_name": bname,
        "grid_shape": data["grid_shape"],
        "raw_rows": len(polar.twa_rows),
        "raw_cols": len(polar.tws_cols),
        "vmg_summary": data["vmg_summary"],
        "raw": data["raw"],
        "created_at": data["created_at"],
    }


@router.api_route("/api/v1/polar/chat", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def polar_chat_removed():
    raise HTTPException(status_code=404, detail="Polar chat is not part of the simulator.")


@router.get("/api/v1/polar/{expedition_id}")
def get_polar(expedition_id: str):
    data, polar = _stored_or_default_polar(expedition_id)
    if "grid" not in data:
        data = {**data, "grid": polar.generate_full_grid().tolist()}
    return data


@router.get("/api/v1/polar/{expedition_id}/summary")
def get_polar_summary(expedition_id: str):
    data, _ = _stored_or_default_polar(expedition_id)
    return {
        "expedition_id": data["expedition_id"],
        "boat_name": data["boat_name"],
        "created_at": data["created_at"],
        "grid_shape": data["grid_shape"],
        "vmg_summary": data["vmg_summary"],
    }


@router.get("/api/v1/polar/{expedition_id}/client")
def get_polar_client(expedition_id: str):
    """Données déjà calculées nécessaires au navigateur, sans la grille 181×61."""
    data, _ = _stored_or_default_polar(expedition_id)
    out = {
        "expedition_id": data["expedition_id"],
        "boat_name": data["boat_name"],
        "created_at": data["created_at"],
        "grid_shape": data["grid_shape"],
        "vmg_summary": data["vmg_summary"],
        "raw": data["raw"],
    }
    if data.get("source"):
        out["source"] = data["source"]
    return out


@router.get("/api/v1/polar/{expedition_id}/speed")
def get_polar_speed(expedition_id: str, twa: float, tws: float):
    polar = _load_polar_data(expedition_id)
    return {
        "expedition_id": expedition_id,
        "twa": twa,
        "tws": tws,
        "speed": float(polar.speed(twa, tws)),
    }
