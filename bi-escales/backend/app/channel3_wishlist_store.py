"""Persisted wishlists (Mongo or in-memory) for treasurer curation."""
from __future__ import annotations

import copy
import threading
import uuid
from typing import Any, Optional

from app.escales.ledger import _mongo_wanted, now_iso

WISHLISTS_COLLECTION = "escales_wishlists"

_lock = threading.Lock()
_memory_wishlists: dict[str, dict] = {}
_store: Any = None


class MemoryWishlistStore:
    async def list_wishlists(self) -> list[dict]:
        with _lock:
            return [copy.deepcopy(row) for row in _memory_wishlists.values()]

    async def get_wishlist(self, wishlist_id: str) -> Optional[dict]:
        with _lock:
            row = _memory_wishlists.get(wishlist_id)
            return copy.deepcopy(row) if row else None

    async def save_wishlist(self, doc: dict) -> dict:
        with _lock:
            stored = copy.deepcopy(doc)
            _memory_wishlists[stored["_id"]] = stored
            return copy.deepcopy(stored)

    async def delete_wishlist(self, wishlist_id: str) -> bool:
        with _lock:
            return _memory_wishlists.pop(wishlist_id, None) is not None


class MongoWishlistStore:
    def __init__(self, db: Any) -> None:
        self._coll = db[WISHLISTS_COLLECTION]
        self._ready = False

    async def _ensure(self) -> None:
        if self._ready:
            return
        await self._coll.create_index("slug", unique=True, sparse=True, name="escales_wishlists_slug")
        self._ready = True

    async def list_wishlists(self) -> list[dict]:
        await self._ensure()
        rows = []
        async for doc in self._coll.find({}).sort("updated_at", -1):
            rows.append(dict(doc))
        return rows

    async def get_wishlist(self, wishlist_id: str) -> Optional[dict]:
        await self._ensure()
        doc = await self._coll.find_one({"_id": wishlist_id})
        return dict(doc) if doc else None

    async def save_wishlist(self, doc: dict) -> dict:
        await self._ensure()
        stored = copy.deepcopy(doc)
        await self._coll.replace_one({"_id": stored["_id"]}, stored, upsert=True)
        return stored

    async def delete_wishlist(self, wishlist_id: str) -> bool:
        await self._ensure()
        result = await self._coll.delete_one({"_id": wishlist_id})
        return result.deleted_count > 0


def reset_wishlist_store() -> None:
    global _store
    _store = None
    with _lock:
        _memory_wishlists.clear()


def get_wishlist_store() -> Any:
    global _store
    if _store is None:
        if _mongo_wanted():
            from app.db import db

            _store = MongoWishlistStore(db)
        else:
            _store = MemoryWishlistStore()
    return _store


def new_wishlist_id() -> str:
    return uuid.uuid4().hex


def normalize_wishlist_item(item: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    qty = int(item.get("quantity") or catalog.get("quantity_needed") or 1)
    minor = int(item.get("target_amount_minor") or catalog["unit_target_amount_minor"])
    currency = str(item.get("target_currency") or catalog["unit_target_currency"]).upper()
    return {
        "channel3_product_id": catalog["channel3_product_id"],
        "project_id": catalog["project_id"],
        "quantity": qty,
        "target_amount_minor": minor,
        "target_currency": currency,
    }
