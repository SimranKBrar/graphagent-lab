"""Per-system execution context: budgets, metrics, event emission, artifacts."""
from __future__ import annotations

import difflib
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import networkx as nx

from .. import config
from ..llm.client import BudgetExceeded, LLMResult


class Cancelled(RuntimeError):
    pass


def compute_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    price_in, price_out = config.price_for(model)
    return round((prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000, 6)


def make_diff(path: str, old: str, new: str) -> str:
    diff = difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                fromfile=f"a/{path}", tofile=f"b/{path}")
    return "".join(diff)[:20000]


@dataclass
class SystemContext:
    run_id: str
    system: str
    task: str
    repo: dict[str, Any]
    workspace: Path
    exec_env: Any                      # repo.workspace.ExecutionEnv
    llm: Any
    model: str
    graph: Optional[nx.MultiDiGraph]
    settings: dict[str, Any]
    emit: Callable[[str, dict[str, Any], Optional[str], Optional[str]], None]
    persist: Callable[[str, Any], None]
    cancel: threading.Event = field(default_factory=threading.Event)

    # live state ----------------------------------------------------------------
    stage: str = ""
    agent: str = ""
    started: float = field(default_factory=time.monotonic)
    explore_report: Optional[dict] = None
    plan: Optional[dict] = None
    test_report: Optional[dict] = None
    edits: list[dict[str, Any]] = field(default_factory=list)
    repairs: list[dict[str, Any]] = field(default_factory=list)
    completion: str = "pending"
    hidden: Optional[dict[str, Any]] = None
    metrics: dict[str, Any] = field(default_factory=dict)

    _inspected: set[str] = field(default_factory=set)
    _modified: set[str] = field(default_factory=set)
    _tool_calls: int = 0
    _llm_calls: int = 0
    _tokens: int = 0
    _cost: float = 0.0
    _graph_queries: int = 0
    _tests_passed: int = 0
    _tests_failed: int = 0

    # ------------------------------------------------------------------ #
    def enter_stage(self, stage: str, agent: str) -> None:
        self.stage = stage
        self.agent = agent

    def check_limits(self) -> None:
        if self.cancel.is_set():
            raise Cancelled("run cancelled by user")
        elapsed = (time.monotonic() - self.started) * 1000
        if elapsed > float(self.settings["timeout_sec"]) * 1000:
            raise BudgetExceeded("time")
        if self._tokens >= int(self.settings["token_budget"]):
            raise BudgetExceeded("tokens")
        if self._tool_calls >= int(self.settings["tool_call_budget"]):
            raise BudgetExceeded("tools")

    # ------------------------------------------------------------------ #
    def on_llm(self, result: LLMResult) -> None:
        self._llm_calls += 1
        self._tokens += result.total_tokens
        self._cost = round(self._cost + compute_cost(
            result.model or self.model, result.prompt_tokens, result.completion_tokens), 6)
        self.emit("llm_call", {
            "agent": self.agent, "model": result.model or self.model, "mock": result.mock,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "total_tokens": result.total_tokens, "duration_ms": result.duration_ms,
        }, self.stage, self.agent)
        self.publish_metrics()

    def on_tool(self, name: str, args: dict, result: Any, ok: bool, duration_ms: int) -> None:
        self._tool_calls += 1
        if name in {"graph_search", "graph_neighbors", "graph_impact", "graph_summary",
                    "gnn_relevance", "gnn_impact"}:
            self._graph_queries += 1
        if name == "read_file" and isinstance(args.get("path"), str):
            self._inspected.add(args["path"])
        preview_src = result if isinstance(result, str) else json.dumps(
            result, ensure_ascii=False, default=str)
        self.emit("tool_call", {"agent": self.agent, "tool": name, "args": _safe_args(args),
                                "call_id": f"t{self._tool_calls}"}, self.stage, self.agent)
        self.emit("tool_result", {"agent": self.agent, "tool": name,
                                  "call_id": f"t{self._tool_calls}", "ok": ok,
                                  "duration_ms": duration_ms,
                                  "preview": preview_src[:800]}, self.stage, self.agent)
        self.publish_metrics()

    def on_graph_visit(self, node_ids: list[str], reason: str) -> None:
        if node_ids:
            self.emit("graph_visit", {"agent": self.agent, "node_ids": node_ids[:60],
                                      "reason": reason}, self.stage, self.agent)

    def on_edit(self, path: str, action: str, old: str, new: str) -> None:
        additions = sum(1 for line in difflib.ndiff(old.splitlines(), new.splitlines())
                        if line.startswith("+ ") )
        deletions = sum(1 for line in difflib.ndiff(old.splitlines(), new.splitlines())
                        if line.startswith("- "))
        self._modified.add(path)
        edit = {"path": path, "action": action,
                "diff": make_diff(path, old, new), "additions": additions,
                "deletions": deletions}
        self.edits.append(edit)
        self.emit("edit_applied", {"path": path, "action": action,
                                   "additions": additions, "deletions": deletions},
                  self.stage, self.agent)
        self.publish_metrics()

    def on_test_report(self, report: dict) -> None:
        self._tests_passed = int(report.get("passed") or 0)
        self._tests_failed = int(report.get("failed") or 0)
        self.publish_metrics()

    def on_repair(self, repair: dict) -> None:
        self.repairs.append(repair)
        self.publish_metrics()

    def publish_metrics(self) -> dict[str, Any]:
        metrics = self.refresh_metrics()
        self.emit("metric_update", dict(metrics), self.stage, self.agent)
        return metrics

    # ------------------------------------------------------------------ #
    def refresh_metrics(self) -> dict[str, Any]:
        self.metrics = {
            "tool_calls": self._tool_calls,
            "llm_calls": self._llm_calls,
            "tokens": self._tokens,
            "cost_usd": self._cost,
            "files_inspected": len(self._inspected),
            "files_modified": len(self._modified),
            "graph_queries": self._graph_queries,
            "tests_passed": self._tests_passed,
            "tests_failed": self._tests_failed,
            "repairs": len(self.repairs),
            "duration_ms": int((time.monotonic() - self.started) * 1000),
            "completion": self.completion,
        }
        if self.hidden:
            self.metrics["hidden_passed"] = int(self.hidden.get("passed") or 0)
            self.metrics["hidden_failed"] = int(self.hidden.get("failed") or 0)
        return self.metrics

    def snapshot(self) -> dict[str, Any]:
        return self.refresh_metrics()

    def save_artifacts(self) -> None:
        """Persist current artifacts to the run_systems row."""
        self.persist("explore_report", self.explore_report)
        self.persist("plan", self.plan)
        self.persist("test_report", self.test_report)
        self.persist("edits", self.edits)
        self.persist("repairs", self.repairs)
        self.persist("metrics", self.refresh_metrics())


def _safe_args(args: dict) -> dict:
    """Keep event payloads small (write_file content is truncated in events)."""
    safe: dict[str, Any] = {}
    for key, value in (args or {}).items():
        if isinstance(value, str) and len(value) > 1200:
            safe[key] = value[:1200] + f"… [{len(value)} chars total]"
        else:
            safe[key] = value
    return safe
