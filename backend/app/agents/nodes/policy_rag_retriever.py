"""policy_rag_retriever node.

Pipeline (per spec -- metadata BEFORE vectors):

1. PRE-FILTER (deterministic SQL): pull only policy rows that can possibly
   apply -- site-wide rows, category rows matching a cart category, SKU rows
   matching a cart SKU -- and drop expired rules.
2. VECTOR SIMILARITY (optional): embed a cart summary and rank the already
   pre-filtered candidates by cosine distance. This enriches
   `retrieved_context` for audit/LLM context but NEVER changes the verdict.
3. RESOLVE: deterministic precedence (SKU > category > site) collapses the
   candidates into ONE ResolvedConstraint. The guardrail and offer generator
   see only this resolved object, never raw chunks.

If embeddings are unavailable (no GEMINI_API_KEY yet, or NULL columns), step
2 is skipped and resolution runs on metadata alone -- still fully correct.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.agents.llm import embed_text, vector_literal
from app.agents.policy_resolution import SCOPE_RANK, resolve_policies
from app.config import get_settings
from app.db.postgres import fetch_all
from app.state import RecoveryState

logger = logging.getLogger(__name__)

# Stage 1 -- exact metadata pre-filter ---------------------------------------
PRE_FILTER_SQL = """
SELECT id, policy_id, scope, sku_id, category, category_exclusion,
       discounts_allowed, discount_cap_pct, margin_floor_pct, valid_until,
       policy_text, (embedding IS NOT NULL) AS has_embedding
FROM merchant_policies
WHERE merchant_id = %s
  AND (valid_until IS NULL OR valid_until > now())
  AND (
        scope = 'site'
     OR (scope = 'category' AND category = ANY(%s))
     OR (scope = 'sku' AND sku_id = ANY(%s))
  )
ORDER BY CASE scope WHEN 'sku' THEN 0 WHEN 'category' THEN 1 ELSE 2 END
"""

# Stage 2 -- cosine-distance rerank within the pre-filtered candidate set ----
DISTANCE_SQL = """
SELECT policy_id, policy_text, scope, sku_id, category,
       embedding <=> %s::vector AS distance
FROM merchant_policies
WHERE merchant_id = %s
  AND id = ANY(%s)
  AND embedding IS NOT NULL
ORDER BY embedding <=> %s::vector
LIMIT 5
"""


def _cart_summary(state: RecoveryState) -> str:
    items = state.get("cart_items") or []
    desc = ", ".join(
        f"{int(it.get('quantity', 1))}x {it.get('name') or it.get('sku_id')} "
        f"({it.get('category', 'uncategorised')})"
        for it in items
    )
    return (
        f"Abandoned cart: {desc}; total value {state.get('cart_value', 0)}. "
        f"Reason: {state.get('abandonment_reason') or 'unknown'}."
    )


async def policy_rag_retriever(state: RecoveryState) -> dict[str, Any]:
    settings = get_settings()
    merchant_id = state.get("merchant_id") or settings.default_merchant_id
    cart_items = state.get("cart_items") or []

    skus = sorted({it["sku_id"] for it in cart_items if it.get("sku_id")})
    categories = sorted({it["category"] for it in cart_items if it.get("category")})

    # ---- Stage 1: metadata pre-filter -------------------------------------
    rows = await fetch_all(PRE_FILTER_SQL, (merchant_id, categories, skus))
    logger.info(
        "policy_rag_retriever: %d candidate policies after metadata pre-filter "
        "(merchant=%s, skus=%s, categories=%s)",
        len(rows), merchant_id, skus, categories,
    )

    # ---- Stage 2: vector similarity on the pre-filtered set ---------------
    retrieved_context: list[dict[str, Any]] = []
    if rows and any(r["has_embedding"] for r in rows):
        query_vec = await asyncio.to_thread(embed_text, _cart_summary(state))
        lit = vector_literal(query_vec)
        if lit is not None:
            ranked = await fetch_all(
                DISTANCE_SQL,
                (lit, merchant_id, [r["id"] for r in rows], lit),
            )
            retrieved_context = [
                {
                    "policy_id": r["policy_id"],
                    "scope": r["scope"],
                    "sku_id": r["sku_id"],
                    "category": r["category"],
                    "distance": float(r["distance"]),
                    "policy_text": r["policy_text"],
                }
                for r in ranked
            ]
    if not retrieved_context:
        # Fallback context without vectors: deterministic precedence order.
        retrieved_context = [
            {
                "policy_id": r["policy_id"],
                "scope": r["scope"],
                "sku_id": r["sku_id"],
                "category": r["category"],
                "distance": None,
                "policy_text": r["policy_text"],
            }
            for r in sorted(rows, key=lambda r: SCOPE_RANK[r["scope"]])
        ]

    # ---- Stage 3: deterministic resolution --------------------------------
    resolved = resolve_policies(cart_items, rows)
    logger.info(
        "policy_rag_retriever: resolved scope=%s allowed=%s cap=%s floor=%s (%s)",
        resolved.scope,
        resolved.discounts_allowed,
        resolved.max_discount_pct,
        resolved.margin_floor_pct,
        ",".join(resolved.source_policy_ids) or "-",
    )

    return {
        "merchant_policy": resolved.model_dump(mode="json"),
        "retrieved_context": retrieved_context,
    }
