"""Async Postgres access (psycopg 3 + pgvector).

A small connection pool is created at app startup (`init_db`) and torn down
at shutdown. The bootstrap step enables the `vector` extension; the full
merchant-policy schema lives in `app/db/schema.py` (step 3).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

_pool: Optional[AsyncConnectionPool] = None

BOOTSTRAP_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;
"""


async def init_db(database_url: str, min_size: int = 1, max_size: int = 8) -> None:
    """Create the connection pool and ensure the pgvector extension exists."""
    global _pool
    if _pool is not None:
        return
    _pool = AsyncConnectionPool(
        conninfo=database_url,
        min_size=min_size,
        max_size=max_size,
        kwargs={"autocommit": True},
        open=False,
    )
    await _pool.open(wait=True)
    async with _pool.connection() as conn:
        await conn.execute(BOOTSTRAP_SQL)
    logger.info("Postgres pool ready (pgvector extension ensured)")


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Postgres pool closed")


def get_pool() -> AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("Database not initialised -- call init_db() first")
    return _pool


async def fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    async with get_pool().connection() as conn:
        cur = await conn.execute(query, params)
        rows = await cur.fetchall()
        cols = [d.name for d in cur.description] if cur.description else []
        return [dict(zip(cols, row)) for row in rows]


async def fetch_one(query: str, params: tuple[Any, ...] = ()) -> Optional[dict[str, Any]]:
    rows = await fetch_all(query, params)
    return rows[0] if rows else None


async def execute(query: str, params: tuple[Any, ...] = ()) -> int:
    """Execute a write query, return rowcount."""
    async with get_pool().connection() as conn:
        cur = await conn.execute(query, params)
        return cur.rowcount or 0
