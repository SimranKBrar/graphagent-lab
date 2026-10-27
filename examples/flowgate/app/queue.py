"""In-memory delivery queue draining events through the dispatcher."""
from __future__ import annotations

from collections import deque
from typing import Any, Callable


class DeliveryQueue:
    def __init__(self, store: Any, send: Callable[[str], None]) -> None:
        self._store = store
        self._send = send
        self._pending: deque[tuple[str, str]] = deque()

    def enqueue(self, endpoint_id: str, url: str) -> None:
        self._pending.append((endpoint_id, url))

    def __len__(self) -> int:
        return len(self._pending)

    def drain(self, endpoints: dict[str, Any]) -> list[str]:
        from .dispatcher import deliver

        results: list[str] = []
        while self._pending:
            endpoint_id, url = self._pending.popleft()
            endpoint = endpoints.get(endpoint_id)
            if endpoint is None:
                continue
            endpoint.url = url
            results.append(deliver(self._store, endpoint, self._send))
        return results
