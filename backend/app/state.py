"""RecoveryState -- the shared schema for one cart-recovery session.

Two layers, deliberately:

1. Pydantic models  -> validation for API payloads, DB rows and anything the
                        LLM produces (offers, resolved policy constraints).
2. `RecoveryState`  -> the LangGraph state channel (TypedDict). Nodes read and
                        return *partial* dicts that LangGraph merges into this
                        state between steps.

`chat_history` uses an append-reducer (`operator.add`) so every node that
returns `{"chat_history": [new_msg]}` *appends* instead of overwriting.
"""
from __future__ import annotations

import operator
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional, TypedDict

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Domain models (Pydantic)
# ---------------------------------------------------------------------------

Outcome = Literal[
    "pending",      # graph in flight
    "link_sent",    # offer + checkout link delivered, awaiting customer action
    "recovered",    # customer completed checkout via relink
    "abandoned",    # customer declined / no interest
    "escalated",    # handed to a human agent
    "expired",      # session TTL lapsed silently (sweep job)
]

OfferKind = Literal[
    "percent_discount",
    "flat_discount",
    "free_shipping",
    "free_gift",
    "loyalty_points",
    "early_access",
    "none",
]


class CartItem(BaseModel):
    sku_id: str
    name: str
    category: str
    price: float = Field(ge=0)
    quantity: int = Field(default=1, ge=1)
    cost_price: float = Field(default=0.0, ge=0)  # used by guardrail margin math


class CustomerHistory(BaseModel):
    customer_id: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    past_orders: int = 0
    lifetime_value: float = 0.0
    previous_abandonments: int = 0
    coupon_redemptions: int = 0


class ResolvedConstraint(BaseModel):
    """The single, *resolved* merchant constraint for this cart.

    Produced by the policy retriever after deterministic precedence
    (SKU-level > category-level > site-wide). The guardrail validates offers
    against this object only -- never against raw policy chunks.
    """

    scope: Literal["sku", "category", "site", "none"] = "none"
    discounts_allowed: bool = True
    max_discount_pct: float = Field(default=0.0, ge=0)
    margin_floor_pct: float = Field(default=0.0, ge=0)
    category_exclusions: list[str] = Field(default_factory=list)
    allowed_incentives: list[str] = Field(
        default_factory=lambda: ["free_shipping", "free_gift", "loyalty_points", "early_access"]
    )
    valid_until: Optional[datetime] = None
    source_policy_ids: list[str] = Field(default_factory=list)
    # Audit trail: which governing rule was applied to each cart item.
    per_item_resolution: list[dict[str, Any]] = Field(default_factory=list)
    rationale: str = ""


class Offer(BaseModel):
    kind: OfferKind = "none"
    discount_pct: float = Field(default=0.0, ge=0)
    flat_amount: float = Field(default=0.0, ge=0)
    message: str = ""
    expires_in_minutes: int = 30


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class GuardrailResult(BaseModel):
    passed: bool
    violations: list[str] = Field(default_factory=list)
    checked_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# LangGraph state channel
# ---------------------------------------------------------------------------


class _RequiredState(TypedDict):
    """Keys that must exist from the moment the graph starts."""

    session_id: str
    cart_items: list[dict[str, Any]]
    cart_value: float
    chat_history: Annotated[list[dict[str, Any]], operator.add]  # append-only
    negotiation_turns: int
    outcome: Outcome


class RecoveryState(_RequiredState, total=False):
    """Full session state threaded through every LangGraph node.

    Optional keys are filled by their owning node:
      customer_history, abandonment_reason -> trigger_listener
      intent                               -> intent_classifier
      merchant_policy, retrieved_context   -> policy_rag_retriever
      offer_made                           -> offer_generator
      guardrail                            -> guardrail_check
      error                                -> any node (failure path)
    """

    customer_history: dict[str, Any]
    abandonment_reason: Optional[str]
    merchant_id: Optional[str]

    # Intent classification (e.g. price_sensitive, comparison_shopping,
    # payment_issue, checkout_friction, gift_browsing, hostile/no_intent)
    intent: Optional[str]

    # Resolved merchant constraint (ResolvedConstraint.model_dump()) +
    # the raw chunks that were considered, for auditability.
    merchant_policy: Optional[dict[str, Any]]
    retrieved_context: list[dict[str, Any]]

    # Current offer on the table (Offer.model_dump()) and how many times the
    # generator has had to retry after a guardrail rejection.
    offer_made: Optional[dict[str, Any]]
    offer_attempts: int

    # Guardrail verdict for the current offer (GuardrailResult.model_dump()).
    guardrail: Optional[dict[str, Any]]

    error: Optional[str]


# ---------------------------------------------------------------------------
# Inbound webhook payload (Razorpay sandbox `cart.abandoned`)
# ---------------------------------------------------------------------------


class CartAbandonedEvent(BaseModel):
    """Shape we accept on POST /webhook/cart-abandoned.

    Razorpay sandbox payloads are free-form per merchant integration, so we
    validate into this canonical shape and reject anything malformed.
    """

    event: str = "cart.abandoned"
    session_id: str
    merchant_id: Optional[str] = None
    cart_items: list[CartItem]
    cart_value: float = Field(ge=0)
    customer: CustomerHistory = Field(default_factory=CustomerHistory)
    abandonment_reason: Optional[str] = None
    payment_failure: Optional[dict[str, Any]] = None  # feeds the RCA panel
    timestamp: Optional[str] = None


class ChatInbound(BaseModel):
    message: str


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def initial_state(payload: CartAbandonedEvent) -> RecoveryState:
    """Build the starting graph state from a validated webhook payload."""
    now = datetime.now(timezone.utc).isoformat()
    return RecoveryState(
        session_id=payload.session_id,
        merchant_id=payload.merchant_id,
        cart_items=[item.model_dump() for item in payload.cart_items],
        cart_value=payload.cart_value,
        customer_history=payload.customer.model_dump(),
        abandonment_reason=payload.abandonment_reason,
        intent=None,
        merchant_policy=None,
        retrieved_context=[],
        offer_made=None,
        offer_attempts=0,
        negotiation_turns=0,
        chat_history=[
            {
                "role": "system",
                "content": f"cart.abandoned received at {now}",
                "ts": now,
            }
        ],
        guardrail=None,
        outcome="pending",
    )
