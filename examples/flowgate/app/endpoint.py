"""Endpoint model: where events are delivered and how many attempts are allowed."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Endpoint:
    id: str
    url: str
    max_attempts: int = 3
    suspended: bool = False
    labels: dict[str, str] = field(default_factory=dict)

    def suspend(self) -> None:
        """Pause deliveries until an operator resumes the endpoint."""
        self.suspended = True

    def resume(self) -> None:
        self.suspended = False
