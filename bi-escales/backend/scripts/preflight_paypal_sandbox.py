#!/usr/bin/env python3
"""Read-only local/test2 preflight. Never authenticates to or writes to PayPal.

Run from backend: python scripts/preflight_paypal_sandbox.py --origin http://127.0.0.1:8011
Reports binding presence only; never prints environment values, bodies or tokens.
A successful local preflight does not verify a sandbox payment or a remote trace.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

BUNDLED = Path(__file__).resolve().parents[1] / "static/.well-known/apple-developer-merchantid-domain-association"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def read(origin: str, path: str) -> tuple[int, str, bytes, bool]:
    try:
        with build_opener(NoRedirect()).open(origin + path, timeout=10) as response:
            body = response.read(1_000_000)
            return response.status, response.headers.get("Content-Type", ""), body, response.url != origin + path
    except HTTPError as error:
        return error.code, "", b"", False
    except (URLError, TimeoutError, OSError):
        return 0, "", b"", False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="http://127.0.0.1:8011")
    args = parser.parse_args()
    origin = args.origin.rstrip("/")
    parsed = urlsplit(origin)
    local = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
    test2 = origin == "https://bi-escales-api-test2.onrender.com"
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path or not (local or test2):
        parser.error("Only loopback HTTP or the existing HTTPS test2 origin is allowed")
    status, _, body, redirected = read(origin, "/api/health")
    try:
        healthy = status == 200 and not redirected and json.loads(body) == {"status": "ok"}
    except (ValueError, UnicodeError):
        healthy = False
    apple_status, media, artifact, redirected = read(origin, "/.well-known/apple-developer-merchantid-domain-association")
    apple_match = (apple_status == 200 and not redirected and media.startswith("application/octet-stream")
                   and hashlib.sha256(artifact).digest() == hashlib.sha256(BUNDLED.read_bytes()).digest())
    print(json.dumps({
        "health_verified": healthy,
        "apple_association": {"http_status": apple_status, "matches_bundled_file": apple_match},
        "binding_presence": {name: name in os.environ for name in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "LANGSMITH_API_KEY")},
        "sandbox_api_verified": False,
        "native_wallet_e2e_verified": False,
        "langsmith_ingestion_verified": False,
        "merchant_console_actions": ["register exact sandbox domain", "confirm merchant association artifact", "enable eligible wallet products"],
    }))
    return 0 if healthy and apple_match else 1


if __name__ == "__main__":
    raise SystemExit(main())
