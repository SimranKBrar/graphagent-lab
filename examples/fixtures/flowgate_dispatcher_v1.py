"""Dispatch decisions: redelivery budget and dead-lettering.

The dispatcher owns the delivery_attempts budget for every endpoint: once an
endpoint has used up its allowed attempts it must be dead-lettered instead of
being redelivered.
"""
from __future__ import annotations

from typing import Any, Callable


def delivery_attempts(store: Any, endpoint_id: str) -> int:
    """Number of delivery attempts recorded for an endpoint."""
    return int(store.count_attempts(endpoint_id))


def can_redeliver(store: Any, endpoint: Any) -> bool:
    """Whether another delivery may be attempted for this endpoint."""
    if getattr(endpoint, "suspended", False):
        return False
    return delivery_attempts(store, endpoint.id) < endpoint.max_attempts


def deliver(store: Any, endpoint: Any, send: Callable[[str], None]) -> str:
    """Attempt one delivery. Returns 'delivered' or 'dead-lettered'."""
    if not can_redeliver(store, endpoint):
        return "dead-lettered"
    store.record_attempt(endpoint.id)
    send(endpoint.url)
    return "delivered"
