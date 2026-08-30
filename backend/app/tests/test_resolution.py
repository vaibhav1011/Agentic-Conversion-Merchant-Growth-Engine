"""Policy resolution tests -- deterministic precedence logic."""
import pytest
from app.agents.policy_resolution import resolve_policies


class TestConflictResolution:
    """Test 3: conflicting policies resolve to the stricter constraint."""

    def test_site_vs_category_conflict(self, sample_policies, electronics_cart):
        """Site-wide 10% vs category no-discount on electronics -> stricter wins."""
        resolved = resolve_policies(electronics_cart, sample_policies)
        assert resolved.discounts_allowed is False
        assert resolved.max_discount_pct == 0.0
        assert resolved.scope == "category"
        assert "POL-CAT-ELEC" in resolved.source_policy_ids

    def test_sku_precedence_overrides_category(self, sample_policies, sku_hp_cart):
        """SKU-HP-X1 clearance 5% overrides category no-discount ban."""
        resolved = resolve_policies(sku_hp_cart, sample_policies)
        assert resolved.scope == "sku"
        assert resolved.discounts_allowed is True
        assert resolved.max_discount_pct == 5.0
        assert "POL-SKU-HP" in resolved.source_policy_ids

    def test_zero_margin_sku_resolved(self, sample_policies, zero_margin_cart):
        """Zero-margin SKU-CONSOLE-Z: discounts_allowed=False, floor=100."""
        resolved = resolve_policies(zero_margin_cart, sample_policies)
        assert resolved.scope == "sku"
        assert resolved.discounts_allowed is False
        assert resolved.max_discount_pct == 0.0
        assert resolved.margin_floor_pct == 100.0

    def test_expired_policy_ignored(self, sample_policies):
        """POL-SITE-LEGACY (expired 2024-12-31) must not apply."""
        cart = [{"sku_id": "SKU-SHIRT", "category": "apparel", "price": 500}]
        resolved = resolve_policies(cart, sample_policies)
        assert "POL-SITE-LEGACY" not in resolved.source_policy_ids
        assert resolved.scope == "site"
        assert resolved.max_discount_pct == 10.0  # active site-wide rule

    def test_mixed_cart_strictest_wins(self, sample_policies):
        """Mixed cart: SKU-HP-X1 (5% allowed) + generic electronics (banned) ->
        overall no discount (strictest)."""
        cart = [
            {"sku_id": "SKU-HP-X1", "category": "electronics", "price": 1500},
            {"sku_id": "SKU-PHONE-B", "category": "electronics", "price": 800},
        ]
        resolved = resolve_policies(cart, sample_policies)
        assert resolved.discounts_allowed is False
        assert resolved.max_discount_pct == 0.0
