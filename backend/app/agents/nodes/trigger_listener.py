"""trigger_listener -- graph entry point.

The webhook handler has already validated the payload into `initial_state`.
This node records the trigger, defaults a missing abandonment_reason, and
appends a system marker to chat_history.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.state import RecoveryState


async def trigger_listener(state: RecoveryState) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    reason = state.get("abandonment_reason") or "unknown"
    return {
        "abandonment_reason": reason,
        "chat_history": [
            {"role": "system", "content": f"cart.abandoned trigger @ {now}; reason={reason}"}
        ],
    }
