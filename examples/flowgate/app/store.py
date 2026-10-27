"""Attempt ledger: records every delivery attempt and dead-letter state."""
from __future__ import annotations


class AttemptStore:
    def __init__(self) -> None:
        self._attempts: dict[str, int] = {}
        self._dead: set[str] = set()

    def count_attempts(self, endpoint_id: str) -> int:
        return self._attempts.get(endpoint_id, 0)

    def record_attempt(self, endpoint_id: str) -> int:
        self._attempts[endpoint_id] = self._attempts.get(endpoint_id, 0) + 1
        return self._attempts[endpoint_id]

    def mark_dead(self, endpoint_id: str) -> None:
        self._dead.add(endpoint_id)

    def is_dead(self, endpoint_id: str) -> bool:
        return endpoint_id in self._dead

    def dead_endpoints(self) -> list[str]:
        return sorted(self._dead)

    def known_endpoints(self) -> list[str]:
        return sorted(set(self._attempts) | self._dead)
