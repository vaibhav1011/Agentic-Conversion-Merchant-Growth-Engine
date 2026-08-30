"""negotiation_node -- reached when a customer replies via POST /chat/{id}.

Appends the inbound user message and bumps negotiation_turns. Routing to
escalation vs. offer-regeneration is encoded as a conditional edge in the
graph (and mirrored in `run_negotiation` for the imperative resume path).
"""
from __future__ import annotations

from typing import Any

from app.state import RecoveryState

# Injected by the /chat handler before resuming the graph.
INBOUND_KEY = "_inbound_message"


async def negotiation_node(state: RecoveryState) -> dict[str, Any]:
    msg = state.get(INBOUND_KEY) or ""
    turns = (state.get("negotiation_turns") or 0) + 1
    delta: dict[str, Any] = {"negotiation_turns": turns}
    if msg:
        delta["chat_history"] = [{"role": "user", "content": msg}]
    return delta
