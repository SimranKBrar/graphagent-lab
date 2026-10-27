"""Reporting rollup tests."""
from app.store import AttemptStore
from reporting.delivery_attempts import rollup, totals


def test_rollup_reports_per_endpoint_totals():
    store = AttemptStore()
    store.record_attempt("ep-1")
    store.record_attempt("ep-1")
    store.record_attempt("ep-2")
    assert rollup(store) == {"ep-1": 2, "ep-2": 1}


def test_totals_aggregates_attempts_and_dead_endpoints():
    store = AttemptStore()
    store.record_attempt("ep-1")
    store.mark_dead("ep-2")
    assert totals(store) == {"attempts": 1, "dead": 1, "endpoints": 2}
