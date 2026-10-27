"""Delivery queue tests."""
from app.endpoint import Endpoint
from app.queue import DeliveryQueue
from app.store import AttemptStore


def _endpoints():
    return {"ep-1": Endpoint(id="ep-1", url="https://a.test/hook"),
            "ep-2": Endpoint(id="ep-2", url="https://b.test/hook")}


def test_drain_delivers_pending_in_order():
    store = AttemptStore()
    sent: list[str] = []
    queue = DeliveryQueue(store, sent.append)
    queue.enqueue("ep-1", "https://a.test/hook")
    queue.enqueue("ep-2", "https://b.test/hook")
    assert queue.drain(_endpoints()) == ["delivered", "delivered"]
    assert len(queue) == 0
    assert sent == ["https://a.test/hook", "https://b.test/hook"]


def test_drain_skips_unknown_endpoints():
    store = AttemptStore()
    queue = DeliveryQueue(store, lambda url: None)
    queue.enqueue("ghost", "https://ghost.test/hook")
    assert queue.drain(_endpoints()) == []
    assert len(queue) == 0


def test_drain_propagates_dead_letter_result():
    store = AttemptStore()
    for _ in range(4):
        store.record_attempt("ep-1")
    queue = DeliveryQueue(store, lambda url: None)
    queue.enqueue("ep-1", "https://a.test/hook")
    assert queue.drain(_endpoints()) == ["dead-lettered"]
    assert store.is_dead("ep-1") is True
