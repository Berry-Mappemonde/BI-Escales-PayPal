"""Persist the Captain LLM daily call counter in MongoDB (UTC date keys).

When ``MONGO_URL`` is unset or storage errors, callers fall back to the
in-memory counter in ``app.core.llm`` without blocking the Captain.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from pymongo import ReturnDocument

from app.db import db, mongo_url

log = logging.getLogger("escales.llm")

COLLECTION_DEFAULT = "llm_daily_counters"
COUNTER_NAME_DEFAULT = "captain"

_storage_warning_logged = False
_mongo_bypass_for_process = False


def collection_name() -> str:
    raw = (os.environ.get("ESCALES_LLM_DAILY_COUNTERS_COLLECTION") or "").strip()
    return raw or COLLECTION_DEFAULT


def counter_name() -> str:
    raw = (os.environ.get("ESCALES_LLM_DAILY_COUNTER_NAME") or "").strip()
    return raw or COUNTER_NAME_DEFAULT


def reset_llm_daily_counter_store() -> None:
    """Clear process-local bypass flags. Tests only; does not delete Mongo data."""
    global _storage_warning_logged, _mongo_bypass_for_process
    _storage_warning_logged = False
    _mongo_bypass_for_process = False


def mongo_persistence_active() -> bool:
    return bool(mongo_url()) and not _mongo_bypass_for_process


def _warn_storage_once(exc: BaseException) -> None:
    global _storage_warning_logged, _mongo_bypass_for_process
    _mongo_bypass_for_process = True
    if _storage_warning_logged:
        return
    _storage_warning_logged = True
    log.warning(
        "LLM daily counter Mongo persistence unavailable; using in-memory fallback (%s)",
        exc.__class__.__name__,
    )


def _collection() -> Any:
    return db[collection_name()]


async def read_count(day_key: str) -> Optional[int]:
    """Return persisted count for ``day_key``, or ``None`` when storage is bypassed."""
    if not mongo_persistence_active():
        return None
    try:
        doc = await _collection().find_one({"_id": day_key})
        if not doc:
            return 0
        return int(doc.get("count") or 0)
    except Exception as exc:
        _warn_storage_once(exc)
        return None


async def consume_one(day_key: str, cap: int) -> Optional[tuple[bool, int]]:
    """Atomically reserve one call when under ``cap``. ``None`` means in-memory fallback."""
    if not mongo_persistence_active():
        return None
    if cap <= 0:
        return False, 0
    try:
        coll = _collection()
        filt: dict[str, Any] = {
            "_id": day_key,
            "$or": [{"count": {"$lt": cap}}, {"count": {"$exists": False}}],
        }
        updated = await coll.find_one_and_update(
            filt,
            {
                "$inc": {"count": 1},
                "$setOnInsert": {"name": counter_name(), "day": day_key},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            doc = await coll.find_one({"_id": day_key})
            count = int((doc or {}).get("count") or cap)
            return False, count
        count = int(updated.get("count") or 0)
        return True, count
    except Exception as exc:
        _warn_storage_once(exc)
        return None
