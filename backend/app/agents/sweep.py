"""Session-expiry sweep.

Silent sessions (customer never replied) are NOT polled forever. Their Redis
blob carries a TTL (`SESSION_TTL_SECONDS`); when it expires, Redis drops it
silently. This sweep periodically scans the `sessions:active` SET (small,
bounded) -- not individual sessions -- and for any member whose blob is gone,
marks the Postgres row `outcome='expired'` and removes it from the set.

This is the cron equivalent the spec asks for: "if a session goes silent,
let it expire and log outcome via a background sweep/cron, don't poll
indefinitely."

Note: we use `expired` (not `abandoned`) to distinguish silent TTL lapse
from an explicit customer decline -- both are non-recovery, but the
distinction matters for the merchant's funnel analytics.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import get_settings
from app.db.postgres import execute
from app.db.redis_client import EXPIRY_INDEX, SESSION_KEY, get_redis

logger = logging.getLogger(__name__)

_EXPIRE_SQL = """
UPDATE recovery_sessions
SET outcome = 'expired', resolved_at = now()
WHERE session_id = %s AND outcome IN ('pending', 'link_sent')
"""


async def sweep_expired_sessions() -> int:
    """Mark silently-expired sessions in Postgres. Returns count marked."""
    r = get_redis()
    active = await r.smembers(EXPIRY_INDEX)
    marked = 0
    for session_id in active:
        if await r.exists(SESSION_KEY.format(session_id=session_id)):
            continue  # still alive
        await execute(_EXPIRE_SQL, (session_id,))
        await r.srem(EXPIRY_INDEX, session_id)
        marked += 1
        logger.info("sweep: session %s expired silently", session_id)
    return marked


async def sweep_loop(interval_seconds: int | None = None) -> None:
    interval = interval_seconds or 60
    logger.info("session-expiry sweep loop started (every %ds)", interval)
    while True:
        try:
            n = await sweep_expired_sessions()
            if n:
                logger.info("sweep: marked %d session(s) expired", n)
        except Exception:  # noqa: BLE001
            logger.exception("sweep loop error")
        await asyncio.sleep(interval)


def start_sweep_task() -> asyncio.Task:
    settings = get_settings()
    return asyncio.create_task(sweep_loop(settings.session_ttl_seconds // 3 or 60))
