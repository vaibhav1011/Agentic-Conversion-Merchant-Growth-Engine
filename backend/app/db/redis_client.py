"""Async Redis client + session-state helpers.

Redis holds *hot* negotiation state (turns, TTL, locks). Postgres is the
system of record for durable session/outcome data.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)

_client: Optional[aioredis.Redis] = None

# Key layout --------------------------------------------------------------
SESSION_KEY = "session:{session_id}"          # hash/json blob of hot state
LOCK_KEY = "lock:webhook:{session_id}"        # distributed webhook lock
EXPIRY_INDEX = "sessions:active"              # SET of active session ids (for sweep)


async def init_redis(redis_url: Optional[str] = None) -> aioredis.Redis:
    global _client
    if _client is None:
        url = redis_url or get_settings().redis_url
        _client = aioredis.from_url(url, decode_responses=True)
        await _client.ping()
        logger.info("Redis connected")
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def get_redis() -> aioredis.Redis:
    if _client is None:
        raise RuntimeError("Redis not initialised -- call init_redis() first")
    return _client


def set_redis_client(client: aioredis.Redis) -> None:
    """Dependency-injection hook (used by tests with fakeredis)."""
    global _client
    _client = client


# --- Session helpers -------------------------------------------------------

async def save_session_state(session_id: str, state: dict[str, Any], ttl: Optional[int] = None) -> None:
    r = get_redis()
    ttl = ttl if ttl is not None else get_settings().session_ttl_seconds
    await r.set(SESSION_KEY.format(session_id=session_id), json.dumps(state), ex=ttl)
    await r.sadd(EXPIRY_INDEX, session_id)
    # Refresh the TTL on every write so active conversations stay alive.
    await r.expire(SESSION_KEY.format(session_id=session_id), ttl)


async def load_session_state(session_id: str) -> Optional[dict[str, Any]]:
    raw = await get_redis().get(SESSION_KEY.format(session_id=session_id))
    if raw is None:
        return None
    return json.loads(raw)


async def drop_session_state(session_id: str) -> None:
    r = get_redis()
    await r.delete(SESSION_KEY.format(session_id=session_id))
    await r.srem(EXPIRY_INDEX, session_id)


async def acquire_webhook_lock(session_id: str, ttl_seconds: int = 30) -> bool:
    """Idempotency guard: returns True only for the first caller for a given
    session_id within the lock window. Prevents duplicate graph runs when
    Razorpay retries/duplicates a webhook delivery."""
    return bool(
        await get_redis().set(
            LOCK_KEY.format(session_id=session_id), "1", nx=True, ex=ttl_seconds
        )
    )
