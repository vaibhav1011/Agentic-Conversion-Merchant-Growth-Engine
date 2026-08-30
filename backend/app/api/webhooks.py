"""Webhook gateway for Razorpay sandbox `cart.abandoned` events.

POST /webhook/cart-abandoned
  - Verifies the Razorpay HMAC signature (when RAZORPAY_WEBHOOK_SECRET set)
  - Validates the payload into a CartAbandonedEvent
  - Acquires a Redis distributed lock keyed on session_id (idempotent:
    duplicate/retried webhooks for the same session do NOT spawn a second
    graph run)
  - Persists the initial state to Redis, then runs the recovery graph in a
    background task and returns 202 immediately (Razorpay requires fast ACKs)

Local dev testing:
  - If ENV=development, signature verification is skipped entirely.
  - Otherwise the endpoint logs the expected HMAC digest on mismatch so you
    can paste it as X-Razorpay-Signature in curl/PowerShell.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status

from app.agents.graph import get_graph
from app.agents.nodes.guardrail_check import TERMINAL_OUTCOMES
from app.config import get_settings
from app.db.redis_client import (
    acquire_webhook_lock,
    load_session_state,
    save_session_state,
)
from app.state import CartAbandonedEvent, initial_state

logger = logging.getLogger(__name__)
router = APIRouter()

DEV_MODE = os.environ.get("ENV", "").lower() == "development"


def compute_signature(raw_body: bytes, secret: str) -> str:
    """HMAC-SHA256 hex digest -- use this to generate X-Razorpay-Signature
    for local curl testing when ENV is NOT development."""
    return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


def _verify_signature(raw_body: bytes, signature: str | None, secret: str) -> None:
    if not secret:
        return  # no secret configured -- skip verification
    if DEV_MODE:
        return  # development mode -- skip verification
    if not signature:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing signature")
    digest = compute_signature(raw_body, secret)
    if not hmac.compare_digest(digest, signature):
        logger.info(
            "webhook signature mismatch -- expected: %s (you can use this as "
            "X-Razorpay-Signature header for local testing)",
            digest,
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid signature")


async def _run_recovery_graph(session_id: str) -> None:
    try:
        state = await load_session_state(session_id)
        if state is None:
            logger.warning("recovery: no initial state for %s", session_id)
            return
        final = await get_graph().ainvoke(state)
        outcome = final.get("outcome", "pending")
        if outcome not in TERMINAL_OUTCOMES:
            await save_session_state(session_id, final)
    except Exception:  # noqa: BLE001
        logger.exception("recovery graph failed for session %s", session_id)


@router.post("/webhook/cart-abandoned", status_code=status.HTTP_202_ACCEPTED)
async def cart_abandoned(request: Request, background: BackgroundTasks) -> dict[str, Any]:
    settings = get_settings()
    raw = await request.body()

    signature = request.headers.get("X-Razorpay-Signature")
    _verify_signature(raw, signature, settings.razorpay_webhook_secret)

    try:
        payload = CartAbandonedEvent.model_validate_json(raw)
    except Exception as exc:
        logger.warning("invalid webhook payload: %s", exc)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid payload: {exc}")

    # Idempotency: a Redis SET NX lock keyed on session_id ensures only one
    # graph run per session, even under webhook retries/duplicates.
    locked = await acquire_webhook_lock(payload.session_id)
    if not locked:
        logger.info("duplicate webhook for session %s -- ignoring", payload.session_id)
        return {"status": "duplicate", "session_id": payload.session_id}

    state = initial_state(payload)
    await save_session_state(payload.session_id, state)
    background.add_task(_run_recovery_graph, payload.session_id)

    return {"status": "accepted", "session_id": payload.session_id}
