"""Génère wind-01..12.npz (float16) à partir du fixture wind_float32_ref.npz."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "wind_float32_ref.npz"
OUT = ROOT / "tests" / "fixtures" / "wind_roses"


def _save_month(month: int, fix: np.lib.npyio.NpzFile) -> None:
    mask = fix["point_month"] == month
    if not np.any(mask):
        return
    idxs = np.where(mask)[0]
    lats = fix["point_lat"][idxs].astype(np.float16)
    lons = fix["point_lon"][idxs].astype(np.float16)
    n = len(idxs)
    sector_pct = np.stack([fix["point_pct"][i] for i in idxs], axis=0).astype(np.float16)
    sector_spd = np.stack([fix["point_spd"][i] for i in idxs], axis=0).astype(np.float16)
    calm = fix["point_calm"][idxs].astype(np.float16).reshape(n, 1)
    gale = fix["point_gale"][idxs].astype(np.float16).reshape(n, 1)
    u = fix["point_u"][idxs].astype(np.float16).reshape(n, 1)
    v = fix["point_v"][idxs].astype(np.float16).reshape(n, 1)
    count = fix["point_count"][idxs].astype(np.int32).reshape(n, 1)
    sea = fix["point_sea"][idxs].astype(bool).reshape(n, 1)
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez(
        OUT / f"wind-{int(month):02d}.npz",
        lats=lats,
        lons=lons,
        sector_pct=sector_pct,
        sector_spd=sector_spd,
        calm_pct=calm,
        gale_pct=gale,
        u_mean=u,
        v_mean=v,
        sample_count=count,
        sea_mask=sea,
        stat=np.array(["rose"]),
    )


def main() -> int:
    fix = np.load(FIXTURE, allow_pickle=False)
    months = sorted({int(m) for m in fix["point_month"]})
    for month in months:
        _save_month(month, fix)
    print(f"wrote {len(months)} archives under {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
