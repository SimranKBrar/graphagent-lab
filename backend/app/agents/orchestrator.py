"""Orchestrator: stateful controller deciding stage transitions.

Primary implementation wires the five stage functions into a LangGraph
StateGraph (conditional edges re-enter explore/plan/edit/test as needed).
An equivalent pure-Python loop (`run_plain`) is used when LangGraph cannot
be imported, so the platform degrades instead of breaking.
"""
from __future__ import annotations

import logging
from typing import Any, TypedDict

from . import stages

logger = logging.getLogger(__name__)


class FlowState(TypedDict, total=False):
    stage: str
    iteration: int
    completion: str
    reason: str
    explore_report: dict
    plan: dict
    test_report: dict
    repair: dict
    next_target: str
    edit_summary: dict


# --------------------------------------------------------------------------- #
# Shared logic
# --------------------------------------------------------------------------- #
def _test_counts(state: dict) -> tuple[int, int]:
    report = state.get("test_report") or {}
    try:
        return int(report.get("passed") or 0), int(report.get("failed") or 0)
    except (TypeError, ValueError):
        return 0, 0


def route_after_test(ctx, state: dict) -> str:
    """'repair' while iterations remain and tests fail, else 'finish'."""
    passed, failed = _test_counts(state)
    iteration = int(state.get("iteration") or 0)
    max_iter = int(ctx.settings["max_iterations"])
    if failed == 0:
        to, reason = "finish", (f"{passed} tests passed" if passed
                                else "no tests executed; finishing without repair")
    elif iteration < max_iter:
        to, reason = "repair", f"{failed} test(s) failing, repair {iteration + 1}/{max_iter}"
    else:
        to, reason = "finish", (f"{failed} test(s) still failing after "
                                f"{max_iter} repair iteration(s)")
    ctx.emit("stage_transition", {"from": "test", "to": to, "reason": reason},
             "test", "test")
    return to


def route_after_repair(ctx, state: dict) -> str:
    target = str(state.get("next_target") or "edit")
    if target not in {"explore", "plan", "edit", "test"}:
        target = "edit"
    ctx.emit("stage_transition", {"from": "repair", "to": target,
                                  "reason": "repair diagnosis target"},
             "repair", "repair")
    return target


def finish_update(ctx, state: dict) -> dict:
    """Terminal node: decide completion from final test state + edits."""
    passed, failed = _test_counts(state)
    if failed > 0:
        completion, reason = "failed", f"{failed} test(s) failing at completion"
    elif passed == 0:
        completion, reason = "partial", "workflow finished but no tests were executed"
    elif not ctx.edits:
        completion, reason = "partial", "workflow finished with no code changes"
    else:
        completion, reason = "success", f"{passed} test(s) passing"
    ctx.completion = completion
    ctx.enter_stage("done", "orchestrator")
    ctx.emit("stage_started", {"stage": "done"}, "done", "orchestrator")
    ctx.emit("log", {"level": "info",
                     "message": f"Orchestrator finished: {completion} — {reason}"},
             "done", "orchestrator")
    return {"stage": "done", "completion": completion, "reason": reason}


# --------------------------------------------------------------------------- #
# LangGraph implementation
# --------------------------------------------------------------------------- #
def _compile(ctx):
    from langgraph.graph import END, START, StateGraph

    builder = StateGraph(FlowState)

    def mk(stage: str, fn):
        def node(state: FlowState) -> dict:
            update: dict[str, Any] = dict(fn(ctx, state) or {})
            update["stage"] = stage
            if stage == "repair":
                update["iteration"] = int(state.get("iteration") or 0) + 1
            return update
        return node

    builder.add_node("explore", mk("explore", stages.stage_explore))
    builder.add_node("plan", mk("plan", stages.stage_plan))
    builder.add_node("edit", mk("edit", stages.stage_edit))
    builder.add_node("test", mk("test", stages.stage_test))
    builder.add_node("repair", mk("repair", stages.stage_repair))
    builder.add_node("finish", lambda state: finish_update(ctx, state))

    builder.add_edge(START, "explore")
    builder.add_conditional_edges("explore", lambda s: "plan", {"plan": "plan"})
    builder.add_conditional_edges("plan", lambda s: "edit", {"edit": "edit"})
    builder.add_conditional_edges("edit", lambda s: "test", {"test": "test"})
    builder.add_conditional_edges(
        "test", lambda s: route_after_test(ctx, s), {"repair": "repair", "finish": "finish"})
    builder.add_conditional_edges(
        "repair", lambda s: route_after_repair(ctx, s),
        {"explore": "explore", "plan": "plan", "edit": "edit", "test": "test"})
    builder.add_edge("finish", END)
    return builder.compile()


# --------------------------------------------------------------------------- #
# Fallback loop (same routers, same stages)
# --------------------------------------------------------------------------- #
def run_plain(ctx) -> dict:
    state: dict[str, Any] = {"stage": "explore", "iteration": 0}
    node = "explore"
    guard = 0
    while node != "done" and guard < 100:
        guard += 1
        if node == "explore":
            state.update(stages.stage_explore(ctx, state))
            state["stage"] = node = "plan"
        elif node == "plan":
            state.update(stages.stage_plan(ctx, state))
            state["stage"] = node = "edit"
        elif node == "edit":
            state.update(stages.stage_edit(ctx, state))
            state["stage"] = node = "test"
        elif node == "test":
            state.update(stages.stage_test(ctx, state))
            node = route_after_test(ctx, state)
        elif node == "repair":
            state.update(stages.stage_repair(ctx, state))
            state["iteration"] = int(state.get("iteration") or 0) + 1
            node = route_after_repair(ctx, state)
        elif node == "finish":
            state.update(finish_update(ctx, state))
            node = "done"
        else:
            break
    return state


def run_orchestrator(ctx) -> dict:
    """Execute the full lifecycle for one system. Raises Cancelled/BudgetExceeded."""
    try:
        app = _compile(ctx)
    except Exception as exc:  # langgraph missing or API drift
        logger.warning("LangGraph unavailable (%s); using built-in orchestrator loop", exc)
        return run_plain(ctx)
    result = app.invoke({"stage": "explore", "iteration": 0})
    return dict(result or {})
