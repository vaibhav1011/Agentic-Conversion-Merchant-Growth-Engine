"""Dashboard data endpoints for the React UI.

GET /dashboard/metrics    -> recovered revenue, conversion rate, escalation rate
GET /dashboard/sessions   -> recent recovery sessions (table)
GET /dashboard/rca        -> payment-failure root-cause aggregation (RCA panel)
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query

from app.db.postgres import fetch_all

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard")


@router.get("/metrics")
async def metrics() -> dict[str, Any]:
    rows = await fetch_all(
        """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE outcome = 'recovered')  AS recovered,
            COUNT(*) FILTER (WHERE outcome = 'link_sent') AS link_sent,
            COUNT(*) FILTER (WHERE outcome = 'escalated') AS escalated,
            COUNT(*) FILTER (WHERE outcome = 'abandoned') AS abandoned,
            COUNT(*) FILTER (WHERE outcome = 'expired')   AS expired,
            COALESCE(SUM(cart_value) FILTER (WHERE outcome = 'recovered'), 0) AS recovered_revenue,
            COALESCE(SUM(cart_value) FILTER (WHERE outcome = 'link_sent'), 0) AS pending_revenue
        FROM recovery_sessions
        """
    )
    m = rows[0] if rows else {}
    total = int(m.get("total") or 0)
    recovered = int(m.get("recovered") or 0)
    link_sent = int(m.get("link_sent") or 0)
    escalated = int(m.get("escalated") or 0)
    return {
        "total_sessions": total,
        "recovered_sessions": recovered,
        "link_sent_sessions": link_sent,
        "escalated_sessions": escalated,
        "abandoned_sessions": int(m.get("abandoned") or 0),
        "expired_sessions": int(m.get("expired") or 0),
        "recovered_revenue": float(m.get("recovered_revenue") or 0),
        "pending_revenue": float(m.get("pending_revenue") or 0),
        "conversion_rate": round(recovered / link_sent, 4) if link_sent else 0.0,
        "escalation_rate": round(escalated / total, 4) if total else 0.0,
    }


@router.get("/sessions")
async def sessions(limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
    rows = await fetch_all(
        """
        SELECT session_id, merchant_id, cart_value, intent, outcome,
               negotiation_turns, checkout_url, created_at, resolved_at,
               offer, resolved_policy, payment_failure, rca
        FROM recovery_sessions
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    return rows


@router.get("/rca")
async def rca() -> list[dict[str, Any]]:
    """Payment-failure root-cause aggregation for the RCA panel."""
    return await fetch_all(
        """
        SELECT
            COALESCE(payment_failure->>'code',
                     payment_failure->>'reason',
                     'unknown') AS failure_code,
            COUNT(*) AS occurrences,
            SUM(cart_value) AS affected_revenue,
            ARRAY_AGG(session_id) FILTER (WHERE outcome = 'abandoned') AS lost_sessions
        FROM recovery_sessions
        WHERE payment_failure IS NOT NULL
        GROUP BY 1
        ORDER BY occurrences DESC
        """
    )
