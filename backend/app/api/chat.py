"""Chat resume endpoint -- customer replies drive the negotiation sub-flow.

POST /chat/{session_id}
  Body: {"message": "..."}
  - Loads the hot session from Redis (404 if expired/unknown)
  - Runs `run_negotiation`, which appends the user message, bumps
    negotiation_turns, and routes to escalation / acceptance / decline /
    offer-regeneration through the guardrail.
  - Returns the assistant's last message + current offer so the dashboard
    can render the live conversation.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.agents.graph import run_negotiation
from app.db.redis_client import load_session_state, save_session_state
from app.agents.nodes.guardrail_check import TERMINAL_OUTCOMES
from app.state import ChatInbound

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat/{session_id}")
async def chat(session_id: str, inbound: ChatInbound) -> dict[str, Any]:
    state = await load_session_state(session_id)
    if state is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "session not found or expired",
        )

    # Block modification of concluded sessions
    if state.get("outcome") in TERMINAL_OUTCOMES:
        return {
            "error": f"This session has been {state['outcome']} and can no longer be modified.",
            "outcome": state["outcome"],
        }

    final = await run_negotiation(state, inbound.message)

    outcome = final.get("outcome", "pending")
    if outcome not in TERMINAL_OUTCOMES:
        await save_session_state(session_id, final)

    chat_history = final.get("chat_history") or []
    last_assistant = next(
        (m["content"] for m in reversed(chat_history) if m.get("role") == "assistant"),
        "",
    )
    return {
        "session_id": session_id,
        "outcome": outcome,
        "negotiation_turns": final.get("negotiation_turns", 0),
        "offer": final.get("offer_made"),
        "reply": last_assistant,
        "guardrail": final.get("guardrail"),
    }
