"""Behavioral tests for dispatch decisions (budget boundary is hidden)."""
from app.dispatcher import can_redeliver, deliver, delivery_attempts
from app.endpoint import Endpoint
from app.store import AttemptStore


def _endpoint(max_attempts=3, suspended=False):
    return Endpoint(id="ep-1", url="https://example.test/hook",
                    max_attempts=max_attempts, suspended=suspended)


def test_attempts_count_starts_at_zero():
    store = AttemptStore()
    assert delivery_attempts(store, "ep-1") == 0


def test_attempts_count_increments_per_delivery():
    store = AttemptStore()
    deliver(store, _endpoint(), lambda url: None)
    assert delivery_attempts(store, "ep-1") == 1


def test_can_redeliver_below_budget():
    store = AttemptStore()
    store.record_attempt("ep-1")
    assert can_redeliver(store, _endpoint(max_attempts=3)) is True


def test_can_redeliver_over_budget():
    store = AttemptStore()
    for _ in range(4):
        store.record_attempt("ep-1")
    assert can_redeliver(store, _endpoint(max_attempts=3)) is False


def test_suspended_endpoint_not_redelivered():
    store = AttemptStore()
    assert can_redeliver(store, _endpoint(suspended=True)) is False


def test_deliver_over_budget_dead_letters_and_marks_dead():
    store = AttemptStore()
    for _ in range(4):
        store.record_attempt("ep-1")
    assert deliver(store, _endpoint(max_attempts=3), lambda url: None) == "dead-lettered"
    assert store.is_dead("ep-1") is True


def test_deliver_records_attempt_and_sends():
    store = AttemptStore()
    sent: list[str] = []
    assert deliver(store, _endpoint(), sent.append) == "delivered"
    assert sent == ["https://example.test/hook"]
    assert store.count_attempts("ep-1") == 1
