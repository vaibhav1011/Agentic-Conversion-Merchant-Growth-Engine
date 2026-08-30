"""checkout_relink -- materialise a Razorpay payment link for the (possibly
discounted) cart and deliver it to the customer.

With sandbox keys configured this calls the Razorpay Payment Links API; in
the absence of keys it synthesises a deterministic stub link so the flow is
fully runnable for development.
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import get_settings
from app.state import RecoveryState

logger = logging.getLogger(__name__)

RAZORPAY_PAYMENT_LINK_URL = "https://api.razorpay.com/v1/payment_links"


def _discounted_value(state: RecoveryState) -> float:
    offer = state.get("offer_made") or {}
    value = float(state.get("cart_value") or 0)
    kind = offer.get("kind")
    if kind == "percent_discount":
        value *= 1.0 - float(offer.get("discount_pct") or 0.0) / 100.0
    elif kind == "flat_discount":
        value -= float(offer.get("flat_amount") or 0.0)
    return max(value, 0.0)


async def _create_payment_link(state: RecoveryState, amount: float) -> str | None:
    settings = get_settings()
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        return None
    auth = base64.b64encode(
        f"{settings.razorpay_key_id}:{settings.razorpay_key_secret}".encode()
    ).decode()
    body = {
        "amount": int(round(amount * 100)),  # paise
        "currency": "INR",
        "reference_id": state["session_id"],
        "description": "Cart recovery offer",
        "customer": {
            "email": (state.get("customer_history") or {}).get("email") or "",
            "contact": (state.get("customer_history") or {}).get("phone") or "",
        },
        "options": {"checkout": {"partial_payment": False}},
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                RAZORPAY_PAYMENT_LINK_URL,
                json=body,
                headers={"Authorization": f"Basic {auth}"},
            )
            r.raise_for_status()
            data = r.json()
            return data.get("short_url") or data.get("url")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Razorpay payment-link call failed (%s) -- stub link", exc)
        return None


async def checkout_relink(state: RecoveryState) -> dict[str, Any]:
    amount = _discounted_value(state)
    url = await _create_payment_link(state, amount)
    if not url:
        url = f"https://rzp.io/r/stub/{state['session_id']}"
        logger.info("checkout_relink: using stub link %s", url)

    offer = dict(state.get("offer_made") or {})
    offer["checkout_url"] = url
    offer["final_amount"] = round(amount, 2)
    now = datetime.now(timezone.utc).isoformat()
    logger.info("checkout_relink: link sent (amount=%.2f) outcome=link_sent", amount)
    return {
        "offer_made": offer,
        "outcome": "link_sent",
        "chat_history": [
            {"role": "assistant", "content": offer.get("message", "") + f" Complete checkout: {url}"}
        ],
    }
