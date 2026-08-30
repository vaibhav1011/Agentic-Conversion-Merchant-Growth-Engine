"""outcome_logger -- durable persistence + Redis cleanup.

Writes the session to Postgres (`recovery_sessions`) as the system of record
and, for terminal outcomes, drops the hot Redis blob. Non-terminal outcomes
(`pending`, `link_sent`) keep Redis alive so the customer can still reply
until the session TTL sweeps them.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.agents.nodes.guardrail_check import TERMINAL_OUTCOMES
from app.db.postgres import execute
from app.db.redis_client import drop_session_state
from app.state import RecoveryState

logger = logging.getLogger(__name__)

UPSERT_SQL = """
INSERT INTO recovery_sessions
    (session_id, merchant_id, cart_value, cart_items, intent,
     abandonment_reason, resolved_policy, offer, negotiation_turns,
     outcome, payment_failure, rca, checkout_url, created_at, resolved_at)
VALUES
    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(NULL, now()), %s)
ON CONFLICT (session_id) DO UPDATE SET
    cart_value         = EXCLUDED.cart_value,
    cart_items         = EXCLUDED.cart_items,
    intent             = EXCLUDED.intent,
    abandonment_reason = EXCLUDED.abandonment_reason,
    resolved_policy    = EXCLUDED.resolved_policy,
    offer              = EXCLUDED.offer,
    negotiation_turns  = EXCLUDED.negotiation_turns,
    outcome            = EXCLUDED.outcome,
    payment_failure    = EXCLUDED.payment_failure,
    rca                = EXCLUDED.rca,
    checkout_url       = EXCLUDED.checkout_url,
    resolved_at        = EXCLUDED.resolved_at
"""


async def outcome_logger(state: RecoveryState) -> dict[str, Any]:
    session_id = state["session_id"]
    outcome = state.get("outcome", "pending")
    now = datetime.now(timezone.utc)
    resolved_at = now if outcome in TERMINAL_OUTCOMES else None

    await execute(
        UPSERT_SQL,
        (
            session_id,
            state.get("merchant_id") or "merchant_demo",
            float(state.get("cart_value") or 0),
            json.dumps(state.get("cart_items") or []),
            state.get("intent"),
            state.get("abandonment_reason"),
            json.dumps(state.get("merchant_policy") or {}),
            json.dumps(state.get("offer_made") or {}),
            int(state.get("negotiation_turns") or 0),
            outcome,
            json.dumps({}) if not state.get("payment_failure") else json.dumps(state["payment_failure"]),
            _rca(state),
            (state.get("offer_made") or {}).get("checkout_url"),
            resolved_at,
        ),
    )

    if outcome in TERMINAL_OUTCOMES:
        await drop_session_state(session_id)

    logger.info("outcome_logger: session=%s outcome=%s turns=%s", session_id, outcome, state.get("negotiation_turns"))
    return {}


def _rca(state: RecoveryState) -> str | None:
    pf = state.get("payment_failure")
    if not pf:
        return None
    return f"payment failure: {pf.get('code') or pf.get('reason') or 'unknown'}"
