"""app.db — MongoDB client (Motor), created on first use.

Modeled on the Blue-Intelligence client: the same timeouts and pool, with
the database name taken from ``DB_NAME`` (default ``bi_escales``). Importing
this module does not open a socket. With ``MONGO_URL`` unset, no client is
built at all.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorClient

# Without socketTimeoutMS an Atlas write can block the single uvicorn loop.
# 300 s matches the shared client: a throttled tier can exceed 60 s.
_CLIENT_KWARGS = {
    "serverSelectionTimeoutMS": 20_000,
    "connectTimeoutMS": 20_000,
    "socketTimeoutMS": 300_000,
    "maxPoolSize": 20,
    "retryWrites": True,
}

DEFAULT_DB_NAME = "bi_escales"

_client: Optional[AsyncIOMotorClient] = None


def mongo_url() -> str:
    return (os.environ.get("MONGO_URL") or "").strip()


def db_name() -> str:
    name = (os.environ.get("DB_NAME") or DEFAULT_DB_NAME).strip()
    return name or DEFAULT_DB_NAME


def reset_db() -> None:
    """Drop the cached client. Tests call this; it does not delete data."""
    global _client
    client = _client
    _client = None
    if client is not None:
        client.close()


def get_client() -> AsyncIOMotorClient:
    """Return the process client. Motor connects on the first operation."""
    global _client
    if _client is None:
        url = mongo_url()
        if not url:
            raise RuntimeError("MONGO_URL is not set")
        _client = AsyncIOMotorClient(url, **_CLIENT_KWARGS)
    return _client


def get_db() -> Any:
    """Return the Motor database. Requires ``MONGO_URL``."""
    return get_client()[db_name()]


class _LazyDatabase:
    """Collection access builds the client. Import alone does not."""

    def _database(self) -> Any:
        return get_client()[db_name()]

    def __getitem__(self, name: str) -> Any:
        return self._database()[name]

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._database(), name)


db = _LazyDatabase()
