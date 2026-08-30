"""Postgres DDL for metadata-enriched merchant-policy chunks.

Each row is one policy *chunk* (natural-language rule) enriched with exact
metadata used for deterministic pre-filtering and rule resolution:

    scope               'sku' | 'category' | 'site'  (precedence: sku > category > site)
    sku_id              set for SKU-level rules
    category            category a rule applies to
    category_exclusion  category a (broader) rule explicitly does NOT apply to
    discounts_allowed   hard on/off switch (e.g. "no discounts on Electronics")
    discount_cap_pct    max % discount this rule permits
    margin_floor_pct    post-discount margin must stay >= this %
    valid_until         expiry; expired rules are ignored by the retriever
    embedding           pgvector embedding of policy_text (768-d, gemini-embedding-001)
"""
from __future__ import annotations

from app.db.postgres import get_pool

EMBEDDING_DIM = 768  # gemini-embedding-001 with output_dimensionality=768

SCHEMA_SQL = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS merchant_policies (
    id                 BIGSERIAL PRIMARY KEY,
    policy_id          TEXT UNIQUE NOT NULL,
    merchant_id        TEXT NOT NULL,
    scope              TEXT NOT NULL CHECK (scope IN ('sku', 'category', 'site')),
    sku_id             TEXT,
    category           TEXT,
    category_exclusion TEXT,
    discounts_allowed  BOOLEAN NOT NULL DEFAULT TRUE,
    discount_cap_pct   NUMERIC(5,2),
    margin_floor_pct   NUMERIC(5,2),
    valid_until        TIMESTAMPTZ,
    policy_text        TEXT NOT NULL,
    embedding          vector({EMBEDDING_DIM}),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_policies_merchant ON merchant_policies (merchant_id);
CREATE INDEX IF NOT EXISTS idx_policies_scope    ON merchant_policies (merchant_id, scope);
CREATE INDEX IF NOT EXISTS idx_policies_sku      ON merchant_policies (sku_id);
CREATE INDEX IF NOT EXISTS idx_policies_category ON merchant_policies (category);

CREATE TABLE IF NOT EXISTS recovery_sessions (
    session_id         TEXT PRIMARY KEY,
    merchant_id        TEXT NOT NULL,
    cart_value         NUMERIC(12,2) NOT NULL,
    cart_items         JSONB NOT NULL,
    intent             TEXT,
    abandonment_reason TEXT,
    resolved_policy    JSONB,
    offer              JSONB,
    negotiation_turns  INTEGER NOT NULL DEFAULT 0,
    outcome            TEXT NOT NULL,
    payment_failure    JSONB,
    rca                TEXT,
    checkout_url       TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_sessions_merchant ON recovery_sessions (merchant_id);
CREATE INDEX IF NOT EXISTS idx_sessions_outcome ON recovery_sessions (outcome);
"""


async def ensure_schema() -> None:
    """Create extension + tables if missing. Idempotent."""
    async with get_pool().connection() as conn:
        await conn.execute(SCHEMA_SQL)
