"""Webhook idempotency + negotiation escalation tests."""
import json
import pytest
import fakeredis.aioredis

from app.db import redis_client
from app.state import CartAbandonedEvent


@pytest.mark.asyncio
async def test_duplicate_webhook_lock(fakeredis_client):
    """Test 5: duplicate webhook calls for the same session_id don't spawn
    duplicate graph runs -- the Redis SET NX lock enforces idempotency."""
    redis_client.set_redis_client(fakeredis_client)

    session_id = "sess-dup-test"
    # First call: lock acquired
    locked1 = await redis_client.acquire_webhook_lock(session_id)
    assert locked1 is True

    # Second call (duplicate webhook): lock NOT acquired
    locked2 = await redis_client.acquire_webhook_lock(session_id)
    assert locked2 is False

    # Third call (still duplicate): still locked
    locked3 = await redis_client.acquire_webhook_lock(session_id)
    assert locked3 is False


@pytest.mark.asyncio
async def test_webhook_lock_different_sessions(fakeredis_client):
    """Different session_ids each get their own lock."""
    redis_client.set_redis_client(fakeredis_client)

    assert await redis_client.acquire_webhook_lock("sess-A") is True
    assert await redis_client.acquire_webhook_lock("sess-B") is True
    assert await redis_client.acquire_webhook_lock("sess-A") is False  # dup


@pytest.mark.asyncio
async def test_session_state_save_load(fakeredis_client):
    """Session state round-trips through Redis."""
    redis_client.set_redis_client(fakeredis_client)

    state = {"session_id": "sess-rt", "cart_value": 1500.0, "negotiation_turns": 0}
    await redis_client.save_session_state("sess-rt", state, ttl=300)

    loaded = await redis_client.load_session_state("sess-rt")
    assert loaded is not None
    assert loaded["session_id"] == "sess-rt"
    assert loaded["cart_value"] == 1500.0


@pytest.mark.asyncio
async def test_session_state_expired(fakeredis_client):
    """Expired session returns None."""
    redis_client.set_redis_client(fakeredis_client)

    # Save with 1-second TTL, then delete
    await redis_client.save_session_state("sess-exp", {"x": 1}, ttl=1)
    # Manually delete to simulate expiry
    await fakeredis_client.delete(redis_client.SESSION_KEY.format(session_id="sess-exp"))

    loaded = await redis_client.load_session_state("sess-exp")
    assert loaded is None
