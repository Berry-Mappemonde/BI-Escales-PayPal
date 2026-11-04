"""Mongo handle for the escales ledger.

``get_ledger`` imports ``db`` only when ``ESCALES_STORE=mongo`` or ``MONGO_URL``
is set. Motor is loaded at that moment. Constructing the client does not open
a socket; pytest keeps ``ESCALES_STORE=memory`` and never reaches this module.
"""
from __future__ import annotations

import os
from typing import Any

_client: Any = None
_db: Any = None

DEFAULT_DB_NAME = "bi_escales"


def reset_db() -> None:
    """Drop the cached client. Tests call this; it does not delete data."""
    global _client, _db
    client = _client
    _client = None
    _db = None
    if client is not None:
        client.close()


def mongo_url() -> str:
    return (os.environ.get("MONGO_URL") or "").strip()


def mongo_db_name() -> str:
    name = (os.environ.get("MONGO_DB") or DEFAULT_DB_NAME).strip()
    return name or DEFAULT_DB_NAME


def get_db() -> Any:
    """Return the Motor database. Requires ``MONGO_URL``."""
    global _client, _db
    if _db is not None:
        return _db
    url = mongo_url()
    if not url:
        raise RuntimeError("MONGO_URL is required when the mongo ledger is selected")
    from motor.motor_asyncio import AsyncIOMotorClient

    _client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=2000)
    _db = _client[mongo_db_name()]
    return _db


class _DBProxy:
    """Object imported as ``db`` so ``from app.db import db`` matches the ledger."""

    def __getitem__(self, name: str) -> Any:
        return get_db()[name]

    def __getattr__(self, name: str) -> Any:
        return getattr(get_db(), name)


db = _DBProxy()
