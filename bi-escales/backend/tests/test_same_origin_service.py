"""M8 : un service, la page et le retour PayPal sur le même hôte."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "smoke_same_origin.py"


def test_smoke_script_checks_the_blueprint_without_calling_render():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "same-origin ok" in completed.stdout


def test_fastapi_serves_the_built_page_and_keeps_the_api(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<title>BI Escales</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("nope", encoding="utf-8")

    import app.main as main

    monkeypatch.setattr(main, "frontend_dist", lambda: dist)
    application = FastAPI()

    @application.get("/api/health")
    def health():
        return {"status": "ok"}

    main.attach_frontend(application)
    client = TestClient(application)
    assert client.get("/api/health").json() == {"status": "ok"}
    page = client.get("/")
    assert page.status_code == 200
    assert "BI Escales" in page.text
    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert "console.log" in asset.text
    assert client.get("/api/escales/schedule").status_code == 404
    escaped = client.get("/../secret.txt")
    assert "nope" not in escaped.text
