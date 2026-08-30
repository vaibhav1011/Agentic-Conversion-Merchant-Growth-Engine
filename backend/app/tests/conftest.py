"""Test fixtures."""
import asyncio
from datetime import datetime, timezone

import pytest
import fakeredis.aioredis

from app.agents.nodes import guardrail_check as _gc  # noqa: F401


@pytest.fixture(scope="session")
def event_loop():
    """Shared event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def fakeredis_client():
    """Fresh fakeredis instance for each test."""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def sample_policies():
    """Mirror of seed_policies build_policies() for unit tests."""
    return [
        {"policy_id": "POL-SITE-10", "scope": "site", "sku_id": None, "category": None,
         "category_exclusion": "gift_cards", "discounts_allowed": True,
         "discount_cap_pct": 10.0, "margin_floor_pct": None, "valid_until": None},
        {"policy_id": "POL-CAT-ELEC", "scope": "category", "sku_id": None,
         "category": "electronics", "category_exclusion": None,
         "discounts_allowed": False, "discount_cap_pct": 0.0,
         "margin_floor_pct": None, "valid_until": None},
        {"policy_id": "POL-CAT-FOOT", "scope": "category", "sku_id": None,
         "category": "footwear", "category_exclusion": None,
         "discounts_allowed": True, "discount_cap_pct": 15.0,
         "margin_floor_pct": 20.0, "valid_until": None},
        {"policy_id": "POL-SKU-HP", "scope": "sku", "sku_id": "SKU-HP-X1",
         "category": "electronics", "category_exclusion": None,
         "discounts_allowed": True, "discount_cap_pct": 5.0,
         "margin_floor_pct": None, "valid_until": None},
        {"policy_id": "POL-SKU-ZERO", "scope": "sku", "sku_id": "SKU-CONSOLE-Z",
         "category": "electronics", "category_exclusion": None,
         "discounts_allowed": False, "discount_cap_pct": 0.0,
         "margin_floor_pct": 100.0, "valid_until": None},
        {"policy_id": "POL-SITE-LEGACY", "scope": "site", "sku_id": None,
         "category": None, "category_exclusion": None,
         "discounts_allowed": True, "discount_cap_pct": 25.0,
         "margin_floor_pct": None,
         "valid_until": datetime(2024, 12, 31, 23, 59, tzinfo=timezone.utc)},
    ]


@pytest.fixture
def electronics_cart():
    """Cart with a generic electronics item (category-level policy applies)."""
    return [{"sku_id": "SKU-PHONE-A", "category": "electronics",
             "price": 1000, "cost_price": 600, "name": "Phone A", "quantity": 1}]


@pytest.fixture
def sku_hp_cart():
    """Cart with SKU-HP-X1 (SKU-level clearance exception)."""
    return [{"sku_id": "SKU-HP-X1", "category": "electronics",
             "price": 1500, "cost_price": 800, "name": "Headphones", "quantity": 1}]


@pytest.fixture
def zero_margin_cart():
    """Cart with SKU-CONSOLE-Z (zero-margin launch item)."""
    return [{"sku_id": "SKU-CONSOLE-Z", "category": "electronics",
             "price": 400, "cost_price": 380, "name": "Console Z", "quantity": 1}]
