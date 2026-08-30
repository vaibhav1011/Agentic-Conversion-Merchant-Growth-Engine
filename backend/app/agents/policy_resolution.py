"""Deterministic policy resolution -- pure Python, no I/O, no LLM.

Given cart items and candidate policy rows (already metadata-pre-filtered),
produce ONE resolved constraint:

1. Precedence per cart item: SKU-level > category-level > site-wide.
   Within a tier, the strictest rule wins (discount-ban > lower cap >
   higher margin floor).
2. A site-wide rule with `category_exclusion` does not govern items of that
   category. Expired rules (`valid_until` in the past) are ignored.
3. Cart-level constraint = the strictest across items, because an offer is
   made on the whole cart: discounts_allowed is AND-ed, caps take the MIN,
   margin floors take the MAX.
4. An item governed by no rule defaults to deny (no monetary discount) --
   merchants must explicitly allow discounts.

Unit-testable without a database: `resolve_policies(cart_items, policies)`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.state import ResolvedConstraint

SCOPE_RANK = {"sku": 0, "category": 1, "site": 2}

DEFAULT_INCENTIVES = ["free_shipping", "free_gift", "loyalty_points", "early_access"]


def _f(value: Any) -> Optional[float]:
    """NUMERIC columns arrive as Decimal; normalise to float/None."""
    if value is None:
        return None
    return float(value)


def is_active(policy: dict[str, Any], now: datetime) -> bool:
    vu = policy.get("valid_until")
    if vu is None:
        return True
    if vu.tzinfo is None:
        vu = vu.replace(tzinfo=timezone.utc)
    return vu > now


def _strictness_key(rule: dict[str, Any]) -> tuple:
    """Lower key == stricter rule."""
    cap = _f(rule.get("discount_cap_pct"))
    floor = _f(rule.get("margin_floor_pct"))
    return (
        bool(rule.get("discounts_allowed", True)),  # False (ban) sorts first
        cap if cap is not None else float("inf"),   # explicit low cap is strict
        -(floor if floor is not None else 0.0),     # high floor is strict
    )


def _strictest(rules: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(rules, key=_strictness_key)[0]


def governing_rule_for_item(
    item: dict[str, Any],
    policies: list[dict[str, Any]],
    now: datetime,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Return (rule, scope) governing one cart item, per precedence."""
    sku = item.get("sku_id")
    category = item.get("category")
    active = [p for p in policies if is_active(p, now)]

    # Tier 1 -- SKU-level
    sku_rules = [
        p for p in active if p.get("scope") == "sku" and p.get("sku_id") == sku
    ]
    if sku_rules:
        return _strictest(sku_rules), "sku"

    # Tier 2 -- category-level
    cat_rules = [
        p
        for p in active
        if p.get("scope") == "category" and p.get("category") == category
    ]
    if cat_rules:
        return _strictest(cat_rules), "category"

    # Tier 3 -- site-wide (respecting category exclusions)
    site_rules = [
        p
        for p in active
        if p.get("scope") == "site" and p.get("category_exclusion") != category
    ]
    if site_rules:
        return _strictest(site_rules), "site"

    return None, None


def resolve_policies(
    cart_items: list[dict[str, Any]],
    policies: list[dict[str, Any]],
    now: Optional[datetime] = None,
) -> ResolvedConstraint:
    """Resolve all applicable policy rules into a single constraint object."""
    now = now or datetime.now(timezone.utc)

    per_item: list[dict[str, Any]] = []
    caps: list[float] = []
    floors: list[float] = []
    allowed = True
    source_ids: list[str] = []
    scopes: set[str] = set()
    exclusions: set[str] = set()
    earliest_valid_until: Optional[datetime] = None

    for item in cart_items:
        rule, scope = governing_rule_for_item(item, policies, now)

        if rule is None:
            # Default deny for ungoverned items (strict interpretation).
            allowed = False
            caps.append(0.0)
            per_item.append(
                {
                    "sku_id": item.get("sku_id"),
                    "policy_id": None,
                    "scope": None,
                    "discounts_allowed": False,
                    "discount_cap_pct": 0.0,
                    "margin_floor_pct": None,
                    "note": "no applicable policy -- default deny",
                }
            )
            continue

        rule_allowed = bool(rule.get("discounts_allowed", True))
        cap = _f(rule.get("discount_cap_pct"))
        floor = _f(rule.get("margin_floor_pct"))

        if not rule_allowed:
            allowed = False
            caps.append(0.0)
        elif cap is not None:
            caps.append(cap)
        if floor is not None:
            floors.append(floor)

        if rule.get("policy_id") and rule["policy_id"] not in source_ids:
            source_ids.append(rule["policy_id"])
        if scope:
            scopes.add(scope)

        vu = rule.get("valid_until")
        if vu is not None:
            if vu.tzinfo is None:
                vu = vu.replace(tzinfo=timezone.utc)
            if earliest_valid_until is None or vu < earliest_valid_until:
                earliest_valid_until = vu

        per_item.append(
            {
                "sku_id": item.get("sku_id"),
                "policy_id": rule.get("policy_id"),
                "scope": scope,
                "discounts_allowed": rule_allowed,
                "discount_cap_pct": cap,
                "margin_floor_pct": floor,
                "note": "",
            }
        )

    # Collect category exclusions from active site-wide rules for context.
    for p in policies:
        if (
            p.get("scope") == "site"
            and p.get("category_exclusion")
            and is_active(p, now)
        ):
            exclusions.add(p["category_exclusion"])

    resolved_scope = "none"
    for s in ("sku", "category", "site"):
        if s in scopes:
            resolved_scope = s
            break

    effective_cap = min(caps) if caps else 0.0
    if not allowed:
        effective_cap = 0.0

    rationale = _build_rationale(per_item, allowed, effective_cap, floors)

    return ResolvedConstraint(
        scope=resolved_scope,
        discounts_allowed=allowed,
        max_discount_pct=round(effective_cap, 2),
        margin_floor_pct=round(max(floors), 2) if floors else 0.0,
        category_exclusions=sorted(exclusions),
        allowed_incentives=list(DEFAULT_INCENTIVES),
        valid_until=earliest_valid_until,
        source_policy_ids=source_ids,
        per_item_resolution=per_item,
        rationale=rationale,
    )


def _build_rationale(
    per_item: list[dict[str, Any]],
    allowed: bool,
    cap: float,
    floors: list[float],
) -> str:
    parts = []
    for entry in per_item:
        if entry["policy_id"] is None:
            parts.append(f"{entry['sku_id']}: no applicable policy (default deny)")
        elif not entry["discounts_allowed"]:
            parts.append(
                f"{entry['sku_id']}: {entry['policy_id']} forbids discounts "
                f"({entry['scope']} scope)"
            )
        else:
            detail = f"cap {entry['discount_cap_pct']}%"
            if entry["margin_floor_pct"] is not None:
                detail += f", margin floor {entry['margin_floor_pct']}%"
            parts.append(
                f"{entry['sku_id']}: governed by {entry['policy_id']} ({detail})"
            )
    verdict = (
        f"Resolved: discounts_allowed={allowed}, max_discount_pct={cap}"
        + (f", margin_floor_pct={max(floors)}" if floors else "")
        + " (strictest applicable constraint wins)."
    )
    return "; ".join(parts) + ". " + verdict
