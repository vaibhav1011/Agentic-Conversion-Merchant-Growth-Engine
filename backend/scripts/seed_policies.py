"""Seed merchant policies as metadata-enriched chunks into Postgres.

Includes a DELIBERATE CONFLICT to exercise rule precedence:

    POL-SITE-10    "10% off site-wide"                     (scope=site)
    POL-CAT-ELEC   "no discounts on Electronics"           (scope=category)
    POL-SKU-HP     "SKU-HP-X1 clearance: up to 5% off"     (scope=sku)

For an Electronics item the site-wide 10% and the category-level ban clash;
resolution must yield the stricter category rule. For SKU-HP-X1 specifically,
the SKU-level exception outranks both (precedence: sku > category > site).
POL-SKU-ZERO is a zero-margin SKU: discount_cap 0 + margin_floor 100 means
only non-monetary incentives may ever be offered. POL-SITE-LEGACY is expired
and must be ignored by the retriever.

Usage:
    docker compose exec backend python -m scripts.seed_policies
    # or locally (from backend/):  python -m scripts.seed_policies

Embeddings are generated with Gemini when GEMINI_API_KEY is configured;
otherwise rows are stored with NULL embeddings and the retriever degrades to
pure metadata precedence (still fully functional).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.config import get_settings
from app.db.postgres import close_db, get_pool, init_db
from app.db.schema import ensure_schema

logger = logging.getLogger("seed")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s :: %(message)s")

DEFAULT_MERCHANT = "merchant_demo"

UPSERT_SQL = """
INSERT INTO merchant_policies
    (policy_id, merchant_id, scope, sku_id, category, category_exclusion,
     discounts_allowed, discount_cap_pct, margin_floor_pct, valid_until,
     policy_text, embedding)
VALUES
    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
ON CONFLICT (policy_id) DO UPDATE SET
    merchant_id        = EXCLUDED.merchant_id,
    scope              = EXCLUDED.scope,
    sku_id             = EXCLUDED.sku_id,
    category           = EXCLUDED.category,
    category_exclusion = EXCLUDED.category_exclusion,
    discounts_allowed  = EXCLUDED.discounts_allowed,
    discount_cap_pct   = EXCLUDED.discount_cap_pct,
    margin_floor_pct   = EXCLUDED.margin_floor_pct,
    valid_until        = EXCLUDED.valid_until,
    policy_text        = EXCLUDED.policy_text,
    embedding          = EXCLUDED.embedding
"""


def build_policies(merchant_id: str) -> list[dict[str, Any]]:
    """Sample policy chunks. All timestamps anchored to UTC."""

    return [
        # --- site-wide ---------------------------------------------------
        {
            "policy_id": "POL-SITE-10",
            "scope": "site",
            "sku_id": None,
            "category": None,
            "category_exclusion": "gift_cards",
            "discounts_allowed": True,
            "discount_cap_pct": 10.0,
            "margin_floor_pct": None,
            "valid_until": None,
            "policy_text": (
                "Site-wide promotion: 10% off on all products store-wide. "
                "Gift cards are excluded from all promotions."
            ),
        },
        # --- category level (CONFLICTS with POL-SITE-10 for electronics) --
        {
            "policy_id": "POL-CAT-ELEC",
            "scope": "category",
            "sku_id": None,
            "category": "electronics",
            "category_exclusion": None,
            "discounts_allowed": False,
            "discount_cap_pct": 0.0,
            "margin_floor_pct": None,
            "valid_until": None,
            "policy_text": (
                "No promotional discounts of any kind may be applied to "
                "products in the Electronics category."
            ),
        },
        {
            "policy_id": "POL-CAT-FOOT",
            "scope": "category",
            "sku_id": None,
            "category": "footwear",
            "category_exclusion": None,
            "discounts_allowed": True,
            "discount_cap_pct": 15.0,
            "margin_floor_pct": 20.0,
            "valid_until": None,
            "policy_text": (
                "Footwear may be discounted up to 15%, and the post-discount "
                "margin must never fall below 20%."
            ),
        },
        # --- SKU level (overrides the electronics category ban for one SKU)
        {
            "policy_id": "POL-SKU-HP",
            "scope": "sku",
            "sku_id": "SKU-HP-X1",
            "category": "electronics",
            "category_exclusion": None,
            "discounts_allowed": True,
            "discount_cap_pct": 5.0,
            "margin_floor_pct": None,
            "valid_until": None,
            "policy_text": (
                "Clearance exception for SKU-HP-X1 wireless headphones: up to "
                "5% off is permitted despite the general electronics discount "
                "ban."
            ),
        },
        # --- zero-margin SKU: only non-monetary incentives allowed --------
        {
            "policy_id": "POL-SKU-ZERO",
            "scope": "sku",
            "sku_id": "SKU-CONSOLE-Z",
            "category": "electronics",
            "category_exclusion": None,
            "discounts_allowed": False,
            "discount_cap_pct": 0.0,
            "margin_floor_pct": 100.0,
            "valid_until": None,
            "policy_text": (
                "SKU-CONSOLE-Z is a zero-margin launch item. Never discount "
                "it. Non-monetary incentives such as free shipping, gifts or "
                "loyalty points are acceptable instead."
            ),
        },
        # --- expired site-wide rule: MUST be ignored by the retriever -----
        {
            "policy_id": "POL-SITE-LEGACY",
            "scope": "site",
            "sku_id": None,
            "category": None,
            "category_exclusion": None,
            "discounts_allowed": True,
            "discount_cap_pct": 25.0,
            "margin_floor_pct": None,
            "valid_until": datetime(2024, 12, 31, 23, 59, tzinfo=timezone.utc),
            "policy_text": (
                "Legacy grand-opening offer: 25% off everything store-wide. "
                "This promotion has ended."
            ),
        },
    ]


def compute_embeddings(texts: list[str]) -> list[Optional[list[float]]]:
    """Embed policy texts with Gemini; degrade to NULLs without an API key."""
    settings = get_settings()
    key = settings.gemini_api_key
    if not key or key.startswith("paste-your"):
        logger.warning(
            "GEMINI_API_KEY not configured — storing NULL embeddings. "
            "Retriever will fall back to metadata-only precedence. "
            "Re-run this script after setting the key to enable vector search."
        )
        return [None] * len(texts)

    from google import genai  # lazy import: only needed when key is present
    from google.genai import types

    client = genai.Client(api_key=key)
    resp = client.models.embed_content(
        model=settings.gemini_embedding_model,
        contents=texts,
        config=types.EmbedContentConfig(output_dimensionality=768),
    )
    return [list(e.values) for e in resp.embeddings]


def _vector_literal(emb: Optional[list[float]]) -> Optional[str]:
    if emb is None:
        return None
    return "[" + ",".join(f"{float(x):.7f}" for x in emb) + "]"


async def run(merchant_id: str) -> None:
    settings = get_settings()
    await init_db(settings.database_url)
    await ensure_schema()

    policies = [
        {"merchant_id": merchant_id, **p} for p in build_policies(merchant_id)
    ]
    embeddings = compute_embeddings([p["policy_text"] for p in policies])

    async with get_pool().connection() as conn:
        for p, emb in zip(policies, embeddings):
            await conn.execute(
                UPSERT_SQL,
                (
                    p["policy_id"],
                    p["merchant_id"],
                    p["scope"],
                    p["sku_id"],
                    p["category"],
                    p["category_exclusion"],
                    p["discounts_allowed"],
                    p["discount_cap_pct"],
                    p["margin_floor_pct"],
                    p["valid_until"],
                    p["policy_text"],
                    _vector_literal(emb),
                ),
            )

    logger.info("Seeded %d policies for merchant '%s'", len(policies), merchant_id)
    logger.info("Deliberate conflict: POL-SITE-10 (10%% site-wide) vs POL-CAT-ELEC (no discounts on Electronics)")
    for p in policies:
        logger.info(
            "  %-16s scope=%-8s sku=%-13s category=%-11s cap=%-5s floor=%-5s allowed=%s",
            p["policy_id"],
            p["scope"],
            str(p["sku_id"]),
            str(p["category"]),
            str(p["discount_cap_pct"]),
            str(p["margin_floor_pct"]),
            p["discounts_allowed"],
        )

    await close_db()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--merchant", default=DEFAULT_MERCHANT, help="merchant id")
    args = parser.parse_args()
    asyncio.run(run(args.merchant))


if __name__ == "__main__":
    main()
