"""AG Grid partner: production build must emit the lazy TreasurerQueueAg chunk."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


def test_vite_build_emits_treasurer_queue_ag_chunk():
    env = {**os.environ, "VITE_ENABLE_AG_GRID": "1"}
    subprocess.run(["npm", "run", "build"], cwd=FRONTEND, env=env, check=True, capture_output=True)
    assets = FRONTEND / "dist" / "assets"
    assert assets.is_dir(), "vite build must produce dist/assets"
    js_files = list(assets.glob("*.js"))
    assert js_files, "expected at least one JS asset"
    names = " ".join(f.name for f in js_files)
    assert "TreasurerQueueAg" in names, f"lazy chunk missing TreasurerQueueAg in: {names}"
