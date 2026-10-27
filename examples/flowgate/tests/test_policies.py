"""Retry budget policy tests."""
from app.endpoint import Endpoint
from policies.delivery_attempts import budget_for, schedule, spent


def test_budget_defaults_by_tier():
    assert budget_for(Endpoint(id="ep-1", url="u")) == 3
    pro = Endpoint(id="ep-2", url="u", labels={"tier": "pro"})
    assert budget_for(pro) == 10


def test_schedule_and_spent():
    ep = Endpoint(id="ep-1", url="u")
    assert len(schedule(ep, streak=0)) == 1
    assert len(schedule(ep, streak=2)) == 3
    assert spent(streak=3, endpoint=ep) is True
    assert spent(streak=2, endpoint=ep) is False
