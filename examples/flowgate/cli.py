"""Tiny CLI: seed a store, deliver one event, print the ledger."""
from __future__ import annotations

import sys

from app.dispatcher import deliver
from app.endpoint import Endpoint
from app.store import AttemptStore


def main(argv: list[str]) -> int:
    store = AttemptStore()
    endpoint = Endpoint(id="ep-1", url="https://example.test/hook", max_attempts=3)
    sent: list[str] = []
    outcome = deliver(store, endpoint, sent.append)
    print(f"{endpoint.id}: {outcome} (attempts={store.count_attempts(endpoint.id)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
