"""Read-only preflight: no cross-origin redirects or hidden sandbox writes."""
from __future__ import annotations

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "sandbox_preflight", Path(__file__).resolve().parents[1] / "scripts/preflight_paypal_sandbox.py",
)
assert SPEC is not None and SPEC.loader is not None
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


@pytest.fixture
def origin():
    paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/must-not-be-requested")
                self.end_headers()
                return
            payload = b'{"status":"ok"}' if self.path == "/api/health" else preflight.BUNDLED.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json" if self.path == "/api/health" else "application/octet-stream")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", paths
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_redirect_is_rejected_before_any_followup_request(origin):
    url, paths = origin
    status, _, body, _ = preflight.read(url, "/redirect")
    assert status == 302
    assert body == b""
    assert paths == ["/redirect"]


def test_local_preflight_reports_bindings_without_claiming_remote_verification(origin, monkeypatch, capsys):
    url, paths = origin
    monkeypatch.setattr("sys.argv", ["preflight", "--origin", url])
    marker = "synthetic-private-preflight-value"
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", marker)
    assert preflight.main() == 0
    output = capsys.readouterr().out
    assert marker not in output
    report = json.loads(output)
    assert report["health_verified"]
    assert report["apple_association"]["matches_bundled_file"]
    assert report["binding_presence"]["PAYPAL_CLIENT_SECRET"] is True
    assert report["sandbox_api_verified"] is False
    assert report["langsmith_ingestion_verified"] is False
    assert paths == ["/api/health", "/.well-known/apple-developer-merchantid-domain-association"]


def test_production_origin_is_refused_before_request(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["preflight", "--origin", "https://escales.naviguide.fr"])
    with pytest.raises(SystemExit) as caught:
        preflight.main()
    assert caught.value.code == 2
    assert "Only loopback HTTP" in capsys.readouterr().err
