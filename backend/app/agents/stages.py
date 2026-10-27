"""The five workflow stages: explore, plan, edit, test, repair.

Each stage enters its agent, assembles the stage input from shared state,
runs the tool loop, records artifacts, and emits the events the frontend
consumes. All three systems execute identical stage code — only the toolset
(systems.build_tools) and the LLM differ.
"""
from __future__ import annotations

import json
from typing import Any

from .base import AgentRunner
from .systems import build_tools


def fence(obj: Any, label: str = "") -> str:
    body = json.dumps(obj if obj is not None else {}, indent=2, ensure_ascii=False)
    return f"```json\n{body}\n```"


# --------------------------------------------------------------------------- #
def stage_explore(ctx, state: dict) -> dict:
    ctx.enter_stage("explore", "explore")
    ctx.emit("stage_started", {"stage": "explore"}, "explore", "explore")
    user = (
        f"## TASK\n{ctx.task}\n\n"
        "Explore the repository and locate the code relevant to this task. Begin with "
        "structure (list_dir, or graph_search/gnn_relevance when available), then narrow "
        "down with grep/reads/traversal. Inspect enough context to guide planning. "
        "Finish with the explore report JSON."
    )
    report = AgentRunner(ctx).run("explore", "explore", user, build_tools(ctx, "explore"))
    report.setdefault("findings", [])
    report.setdefault("symbols", [])
    report.setdefault("files_inspected", [])
    report.setdefault("notes", "")
    ctx.explore_report = report
    ctx.emit("explore_report", {
        "findings": report["findings"][:10], "symbols": report["symbols"][:25],
        "files_inspected": report["files_inspected"][:25],
        "notes": str(report.get("notes", ""))[:400],
    }, "explore", "explore")
    ctx.emit("stage_finished", {"stage": "explore", "ok": True}, "explore", "explore")
    return {"explore_report": report}


# --------------------------------------------------------------------------- #
def stage_plan(ctx, state: dict) -> dict:
    ctx.enter_stage("plan", "plan")
    ctx.emit("stage_started", {"stage": "plan"}, "plan", "plan")
    explore = state.get("explore_report") or ctx.explore_report or {}
    user = (
        f"## TASK\n{ctx.task}\n\n"
        f"## EXPLORE REPORT\n{fence(explore)}\n\n"
        "Produce a concrete, ordered implementation plan: which files and functions "
        "change, in what order, and the side effects to verify. You may inspect more "
        "files or query the graph first. Finish with the plan JSON."
    )
    plan = AgentRunner(ctx).run("plan", "plan", user, build_tools(ctx, "plan"))
    plan.setdefault("steps", [])
    plan.setdefault("risks", [])
    ctx.plan = plan
    ctx.emit("plan_generated", {
        "steps": [{"id": s.get("id"), "description": str(s.get("description", ""))[:300],
                   "files": s.get("files") or [], "symbols": s.get("symbols") or []}
                  for s in plan["steps"][:12]],
        "risks": [str(r)[:200] for r in plan["risks"][:6]],
    }, "plan", "plan")
    ctx.emit("stage_finished", {"stage": "plan", "ok": True}, "plan", "plan")
    return {"plan": plan}


# --------------------------------------------------------------------------- #
def stage_edit(ctx, state: dict) -> dict:
    ctx.enter_stage("edit", "edit")
    ctx.emit("stage_started", {"stage": "edit"}, "edit", "edit")
    before = len(ctx.edits)
    explore = state.get("explore_report") or ctx.explore_report or {}
    plan = state.get("plan") or ctx.plan or {}
    user = (
        f"## TASK\n{ctx.task}\n\n"
        f"## EXPLORE REPORT\n{fence(explore)}\n\n"
        f"## IMPLEMENTATION PLAN\n{fence(plan)}\n\n"
        "Implement the plan now using write_file with complete file contents. Apply the "
        "minimal change that correctly solves the task; do not touch unrelated code. "
        "Finish with the edit summary JSON."
    )
    summary = AgentRunner(ctx).run("edit", "edit", user, build_tools(ctx, "edit"))
    new_edits = ctx.edits[before:]
    if not new_edits:
        ctx.emit("log", {"level": "info", "message":
                         "Edit stage completed without file modifications"}, "edit", "edit")
    ctx.emit("stage_finished", {"stage": "edit", "ok": True, "edits": len(new_edits)},
             "edit", "edit")
    return {"edit_summary": summary}


# --------------------------------------------------------------------------- #
def stage_test(ctx, state: dict) -> dict:
    ctx.enter_stage("test", "test")
    ctx.emit("stage_started", {"stage": "test"}, "test", "test")
    plan = state.get("plan") or ctx.plan or {}
    user = (
        f"## TASK\n{ctx.task}\n\n"
        f"## PLAN\n{fence(plan)}\n\n"
        "Run the required validation suite with run_tests. Report an accurate structured "
        "test report JSON: total passed, total failed, and every failure's name, file and "
        "error message. If the suite cannot run, say so in the summary."
    )
    report = AgentRunner(ctx).run("test", "test", user, build_tools(ctx, "test"))
    report.setdefault("passed", 0)
    report.setdefault("failed", 0)
    report.setdefault("failures", [])
    report.setdefault("summary", "")
    try:
        report["passed"] = int(report["passed"])
        report["failed"] = int(report["failed"])
    except (TypeError, ValueError):
        report["passed"], report["failed"] = 0, 0
    ctx.test_report = report
    ctx.on_test_report(report)
    ctx.emit("test_results", {
        "passed": report["passed"], "failed": report["failed"],
        "failures": report["failures"][:10],
        "summary": str(report.get("summary", ""))[:300],
        "hidden": False,
    }, "test", "test")
    ctx.emit("stage_finished", {"stage": "test", "ok": report["failed"] == 0},
             "test", "test")
    return {"test_report": report}


# --------------------------------------------------------------------------- #
def stage_repair(ctx, state: dict) -> dict:
    ctx.enter_stage("repair", "repair")
    ctx.emit("stage_started", {"stage": "repair"}, "repair", "repair")
    before = len(ctx.edits)
    report = state.get("test_report") or ctx.test_report or {}
    repairs = state.get("repairs") or ctx.repairs or []
    user = (
        f"## TASK\n{ctx.task}\n\n"
        f"## TEST REPORT\n{fence(report)}\n\n"
        f"## PREVIOUS REPAIR ATTEMPTS\n{fence(repairs) if repairs else '(none)'}\n\n"
        "Diagnose the failures against the code (read/grep as needed). If you can identify "
        "the root cause, apply a corrective write_file change, then reply with the repair "
        "JSON including target_stage (explore|plan|edit|test) — use 'test' when you have "
        "applied a fix that should make the suite pass."
    )
    payload = AgentRunner(ctx).run("repair", "repair", user, build_tools(ctx, "repair"))
    target = str(payload.get("target_stage") or "edit")
    if target not in {"explore", "plan", "edit", "test"}:
        target = "edit"
    payload["target_stage"] = target
    payload.setdefault("diagnosis", "")
    payload.setdefault("root_cause", "")
    payload.setdefault("notes", "")
    payload["edits_applied"] = len(ctx.edits) - before
    ctx.on_repair(payload)
    ctx.emit("repair_attempt", {
        "diagnosis": str(payload.get("diagnosis", ""))[:600],
        "root_cause": str(payload.get("root_cause", ""))[:600],
        "target_stage": target, "edits_applied": payload["edits_applied"],
    }, "repair", "repair")
    ctx.emit("stage_finished", {"stage": "repair", "ok": True}, "repair", "repair")
    return {"repair": payload, "next_target": target}
