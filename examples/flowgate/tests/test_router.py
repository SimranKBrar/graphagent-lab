"""Topic router tests."""
from app.endpoint import Endpoint
from app.router import Router


def _endpoints():
    return {"ep-1": Endpoint(id="ep-1", url="https://a.test/hook"),
            "ep-2": Endpoint(id="ep-2", url="https://b.test/hook"),
            "ep-3": Endpoint(id="ep-3", url="https://c.test/hook", suspended=True)}


def test_route_returns_only_subscribed_live_endpoints():
    router = Router()
    router.subscribe("orders", "ep-1")
    router.subscribe("orders", "ep-3")
    router.subscribe("billing", "ep-2")
    assert router.route("orders", _endpoints()) == ["ep-1"]


def test_endpoints_for_is_sorted_and_empty_safe():
    router = Router()
    assert router.endpoints_for("unknown") == []
    router.subscribe("t", "ep-2")
    router.subscribe("t", "ep-1")
    assert router.endpoints_for("t") == ["ep-1", "ep-2"]
