"""Dashboard rollups over delivery_attempts counters.

Aggregates raw attempt counters from the store into per-endpoint and
per-topic rollups for the operations dashboard. Read-only reporting: nothing
here participates in dispatch decisions.
"""
from __future__ import annotations

from typing import Any


def rollup(store: Any) -> dict[str, int]:
    """Per-endpoint attempt totals from the ledger."""
    return {eid: store.count_attempts(eid) for eid in store.known_endpoints()}


def totals(store: Any) -> dict[str, int]:
    """Aggregate counters: attempts recorded, endpoints dead-lettered."""
    per_endpoint = rollup(store)
    return {
        "attempts": sum(per_endpoint.values()),
        "dead": len(store.dead_endpoints()),
        "endpoints": len(per_endpoint),
    }
