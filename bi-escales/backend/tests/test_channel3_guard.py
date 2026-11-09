"""C3-08 — no Channel3 checkout/purchase/order usage."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.channel3_client import Channel3GuardError, assert_channel3_mcp_tool, assert_channel3_read_only_url

_CHANNEL3_COMMERCE_URL = re.compile(
    r"(?:trychannel3|channel3\.com)[^\s\"']*/(?:checkout|purchase|orders?)(?:/|$|[\"'?&])",
    re.IGNORECASE,
)
_CHANNEL3_COMMERCE_LITERAL = re.compile(
    r"[\"'][^\"']*(?:trychannel3|channel3)[^\"']*/(?:checkout|purchase|orders?)",
    re.IGNORECASE,
)


def test_guard_blocks_checkout_urls():
    with pytest.raises(Channel3GuardError):
        assert_channel3_read_only_url("https://api.trychannel3.com/v1/checkout")
    with pytest.raises(Channel3GuardError):
        assert_channel3_read_only_url("https://ucp.trychannel3.com/mcp/order")


def test_guard_allows_mcp_search():
    assert_channel3_read_only_url("https://ucp.trychannel3.com/mcp")
    assert_channel3_mcp_tool("search_catalog")


def test_backend_app_has_no_forbidden_channel3_commerce_endpoints():
    app_root = Path(__file__).resolve().parent.parent / "app"
    offenders: list[str] = []
    for path in sorted(app_root.rglob("*.py")):
        rel = path.relative_to(app_root.parent)
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "_BLOCKED_CHANNEL3" in line or "assert_channel3" in line:
                continue
            if _CHANNEL3_COMMERCE_URL.search(line) or _CHANNEL3_COMMERCE_LITERAL.search(line):
                offenders.append(f"{rel}:{lineno}")
    assert not offenders, f"Channel3 checkout/purchase/order refs: {', '.join(offenders)}"
