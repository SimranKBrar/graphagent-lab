"""Attempt ledger tests."""
from app.store import AttemptStore


def test_count_defaults_to_zero():
    store = AttemptStore()
    assert store.count_attempts("missing") == 0


def test_record_and_count():
    store = AttemptStore()
    store.record_attempt("ep-1")
    store.record_attempt("ep-1")
    assert store.count_attempts("ep-1") == 2
    assert store.known_endpoints() == ["ep-1"]


def test_dead_letter_tracking():
    store = AttemptStore()
    store.record_attempt("ep-1")
    store.record_attempt("ep-2")
    store.mark_dead("ep-2")
    assert store.is_dead("ep-2") is True
    assert store.is_dead("ep-1") is False
    assert store.dead_endpoints() == ["ep-2"]
    assert store.known_endpoints() == ["ep-1", "ep-2"]
