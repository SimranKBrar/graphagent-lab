"""Retry budget policy: how many delivery_attempts an endpoint is granted.

This module answers a scheduling question -- given an endpoint's tier and the
current failure streak, how big is its retry budget and when does the next
backoff window open? It is deliberately policy-only: the dispatch loop in the
app package decides what to do with a spent budget.
"""
from __future__ import annotations

TIER_LIMITS = {"free": 3, "pro": 10, "enterprise": 25}


def budget_for(endpoint) -> int:
    """Retry budget granted to an endpoint for its current billing tier."""
    tier = getattr(endpoint, "labels", {}).get("tier", "free")
    return TIER_LIMITS.get(tier, TIER_LIMITS["free"])


def schedule(endpoint, streak: int) -> list[float]:
    """Backoff schedule (seconds) for a failure streak under the policy."""
    budget = budget_for(endpoint)
    base = 2.0
    return [base * (2 ** min(i, 6)) for i in range(min(streak + 1, budget))]


def spent(streak: int, endpoint) -> bool:
    """Whether the policy considers the endpoint's allowance consumed."""
    return streak >= budget_for(endpoint)
