"""Hidden suite: the exact budget boundary that the visible suite avoids.

An endpoint that has used its full delivery_attempts allowance must be
dead-lettered -- not granted one more delivery.
"""
from app.dispatcher import can_redeliver, deliver
from app.endpoint import Endpoint
from app.queue import DeliveryQueue
from app.store import AttemptStore


def _endpoint(max_attempts=3):
    return Endpoint(id="ep-1", url="https://example.test/hook",
                    max_attempts=max_attempts)


def _store_at_budget(budget: int) -> AttemptStore:
    store = AttemptStore()
    for _ in range(budget):
        store.record_attempt("ep-1")
    return store


def test_can_redeliver_false_at_exact_budget():
    store = _store_at_budget(3)
    assert can_redeliver(store, _endpoint(max_attempts=3)) is False


def test_deliver_at_exact_budget_dead_letters():
    store = _store_at_budget(3)
    assert deliver(store, _endpoint(max_attempts=3), lambda url: None) == "dead-lettered"


def test_no_extra_attempt_recorded_at_budget():
    store = _store_at_budget(3)
    deliver(store, _endpoint(max_attempts=3), lambda url: None)
    assert store.count_attempts("ep-1") == 3


def test_endpoint_marked_dead_at_budget():
    store = _store_at_budget(3)
    deliver(store, _endpoint(max_attempts=3), lambda url: None)
    assert store.is_dead("ep-1") is True


def test_send_not_called_at_budget():
    store = _store_at_budget(3)
    sent: list[str] = []
    deliver(store, _endpoint(max_attempts=3), sent.append)
    assert sent == []


def test_tight_budget_stops_after_first_delivery():
    store = AttemptStore()
    sent: list[str] = []
    ep = _endpoint(max_attempts=1)
    assert deliver(store, ep, sent.append) == "delivered"
    assert deliver(store, ep, sent.append) == "dead-lettered"
    assert store.count_attempts("ep-1") == 1
    assert len(sent) == 1


def test_queue_drain_dead_letters_at_budget():
    store = _store_at_budget(3)
    sent: list[str] = []
    queue = DeliveryQueue(store, sent.append)
    queue.enqueue("ep-1", "https://example.test/hook")
    queue.enqueue("ep-1", "https://example.test/hook")
    results = queue.drain({"ep-1": _endpoint(max_attempts=3)})
    assert results == ["dead-lettered", "dead-lettered"]
    assert sent == []
    assert store.count_attempts("ep-1") == 3
