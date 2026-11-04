"""Base URL Blue Intelligence. No implicit production host.

Production sets BI_API_URL. Everywhere else (dev, preview, CI, tests) the
helper returns None and logs once, so callers skip the network and reuse
the fallback they already use when the upstream is down.
"""
from __future__ import annotations

import logging
import os
import threading

log = logging.getLogger("naviguide-simulator.bi")

_log_lock = threading.Lock()
_disabled_logged = False


class BiDisabled(RuntimeError):
    """BI_API_URL is unset or empty. No upstream request was made."""


def bi_base() -> str | None:
    raw = (os.getenv("BI_API_URL") or "").strip()
    if not raw:
        _log_disabled()
        return None
    return raw.rstrip("/")


def _log_disabled() -> None:
    global _disabled_logged
    with _log_lock:
        if _disabled_logged:
            return
        _disabled_logged = True
    log.warning("BI disabled: BI_API_URL is not set")
