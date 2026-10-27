"""Core unit tests: graph construction, pytest parsing, JSON extraction,
orchestrator routing decisions."""
from __future__ import annotations

import types
from pathlib import Path

import pytest

from app.agents.orchestrator import (finish_update, route_after_repair,
                                     route_after_test)
from app.agents.testparse import parse_pytest
from app.graph import builder, tools as gtools
from app.llm.jsonutil import extract_json

SAMPLE = Path(__file__).resolve().parents[2] / "examples" / "sample_repo"


# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def graph():
    g, stats = builder.build_graph(SAMPLE)
    return g, stats


def test_graph_shapes(graph):
    g, stats = graph
    assert stats["nodes"] > 30 and stats["edges"] > 50
    kinds = stats["by_kind"]
    assert kinds.get("module", 0) >= 8
    assert kinds.get("function", 0) >= 10
    assert kinds.get("test_function", 0) >= 15
    assert kinds.get("class", 0) >= 5


def test_call_and_test_edges(graph):
    g, _ = graph
    caller = "orders/service.py::create_order"
    callees = {b for a, b, d in g.out_edges(caller, data=True)
               if d.get("type") in {"calls", "tests"}}
    assert "orders/validation.py::validate_item" in callees
    assert any(n.startswith("tests/test_service.py::test_") for n in g.predecessors(caller)) or \
        any(a.startswith("tests/") for a, b, d in g.in_edges(caller, data=True)
            if d.get("type") == "tests")


def test_imports_and_inheritance(graph):
    g, _ = graph
    imports = [(a, b) for a, b, d in g.edges(data=True) if d.get("type") == "imports"]
    assert any(b == "orders/validation.py" for _, b in imports)
    inherits = [(a, b) for a, b, d in g.edges(data=True) if d.get("type") == "inherits"]
    # repository failsaves subclass OrderRepository
    assert any(b.endswith("::OrderRepository") for _, b in inherits)


def test_graph_queries(graph):
    g, _ = graph
    hits = gtools.search(g, "create_order")
    assert hits and hits[0]["label"] == "create_order"
    node_id = hits[0]["id"]
    impact = gtools.impact(g, node_id, depth=2)
    assert any(n["id"].startswith("tests/") for n in impact["affected"])
    detail = gtools.node_detail(g, node_id)
    assert detail and detail["callers"] is not None
    rel = gtools.relevance(g, "fix quantity validation in create_order")
    assert rel and rel[0]["score"] > 0


# --------------------------------------------------------------------------- #
def test_parse_pytest_summary():
    out = """
FAILED tests/test_service.py::test_reserves - AssertionError: stock not changed
tests/test_service.py:42: in test_reserves
E   AssertionError: 5 != 3
=========================== 15 passed, 1 failed in 0.12s ===========================
"""
    parsed = parse_pytest(out, exit_code=1)
    assert parsed["passed"] == 15
    assert parsed["failed"] == 1
    assert parsed["failures"][0]["name"] == "test_reserves"
    assert parsed["failures"][0]["line"] == 42
    assert parsed["ok"] is False


def test_parse_pytest_no_tests():
    parsed = parse_pytest("collected 0 items\nno tests ran in 0.01s", exit_code=5)
    assert parsed["no_tests"] is True and parsed["passed"] == 0


# --------------------------------------------------------------------------- #
def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('Sure.\n```json\n{"steps": [1, 2]}\n```') == {"steps": [1, 2]}
    assert extract_json('{"a": {"b": 2}, "c": 3,}') == {"a": {"b": 2}, "c": 3}  # trailing comma
    assert extract_json("no json here") is None
    assert extract_json('{"msg": "braces } inside", "n": 1}')["n"] == 1


# --------------------------------------------------------------------------- #
def fake_ctx(**overrides):
    events = []
    ctx = types.SimpleNamespace(
        settings={"max_iterations": 2},
        edits=[{"path": "x.py"}],
        completion="pending",
        emit=lambda t, p, s=None, a=None: events.append((t, p)),
        enter_stage=lambda stage, agent: None,
        events=events,
    )
    for key, value in overrides.items():
        setattr(ctx, key, value)
    return ctx


def test_route_after_test():
    ctx = fake_ctx()
    assert route_after_test(ctx, {"test_report": {"passed": 3, "failed": 0}}) == "finish"
    assert route_after_test(ctx, {"test_report": {"passed": 0, "failed": 0}}) == "finish"
    assert route_after_test(ctx, {"test_report": {"passed": 1, "failed": 2}}) == "repair"
    # iteration exhausted -> finish
    state = {"test_report": {"passed": 1, "failed": 2}, "iteration": 2}
    assert route_after_test(ctx, state) == "finish"
    assert any(t == "stage_transition" for t, _ in ctx.events)


def test_route_after_repair_targets():
    ctx = fake_ctx()
    assert route_after_repair(ctx, {"next_target": "test"}) == "test"
    assert route_after_repair(ctx, {"next_target": "bogus"}) == "edit"


def test_finish_update_decides_completion():
    ctx = fake_ctx()
    done = finish_update(ctx, {"test_report": {"passed": 4, "failed": 0}})
    assert done["completion"] == "success"
    ctx2 = fake_ctx(edits=[])
    assert finish_update(ctx2, {"test_report": {"passed": 4, "failed": 0}})["completion"] == "partial"
    ctx3 = fake_ctx()
    assert finish_update(ctx3, {"test_report": {"passed": 0, "failed": 3}})["completion"] == "failed"
