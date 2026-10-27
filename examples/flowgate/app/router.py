"""Route incoming events to endpoints by topic subscription."""
from __future__ import annotations

from typing import Any


class Router:
    def __init__(self) -> None:
        self._routes: dict[str, set[str]] = {}

    def subscribe(self, topic: str, endpoint_id: str) -> None:
        self._routes.setdefault(topic, set()).add(endpoint_id)

    def endpoints_for(self, topic: str) -> list[str]:
        return sorted(self._routes.get(topic, set()))

    def route(self, topic: str, endpoints: dict[str, Any]) -> list[str]:
        return [eid for eid in self.endpoints_for(topic)
                if eid in endpoints and not endpoints[eid].suspended]
