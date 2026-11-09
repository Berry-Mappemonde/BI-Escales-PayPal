"""C3-08 — no Channel3 checkout/purchase/order usage."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.channel3_client import Channel3GuardError, assert_channel3_mcp_tool, assert_channel3_read_only_url

_HTTP_FORBIDDEN = re.compile(
    r"https?://[^\s\"']+/(?:checkout|purchase|orders?)(?:/|$)",
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


def test_channel3_client_source_has_no_forbidden_http_endpoints():
    root = Path(__file__).resolve().parent.parent / "app"
    client_src = (root / "channel3_client.py").read_text(encoding="utf-8")
    assert not _HTTP_FORBIDDEN.search(client_src), "channel3_client must not call checkout/purchase/order URLs"
