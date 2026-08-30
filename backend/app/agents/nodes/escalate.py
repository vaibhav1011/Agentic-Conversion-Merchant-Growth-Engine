"""escalate_to_human_node -- hand a stuck/over-budget session to a human."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.state import RecoveryState

logger = logging.getLogger(__name__)


async def escalate_to_human_node(state: RecoveryState) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    reason = state.get("error") or "escalation threshold reached"
    logger.warning("escalate_to_human_node: %s (%s)", state.get("session_id"), reason)
    return {
        "outcome": "escalated",
        "chat_history": [
            {
                "role": "system",
                "content": f"escalated to human agent @ {now}; reason={reason}",
            }
        ],
    }
