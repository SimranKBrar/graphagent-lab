"""Run creation and execution: isolated workspaces, parallel systems, budgets.

Each run spawns one thread per selected system; each system runs the
explore -> plan -> edit -> test -> repair lifecycle inside its own repository
copy (Docker-preferred isolation with local fallback), emitting events into
the shared run event log consumed by the SSE endpoint and dashboard.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from typing import Any, Optional

from .. import config, db
from ..benchmark import evaluate, tasks as task_catalog
from ..graph import store as graph_store
from ..llm.client import BudgetExceeded, get_llm
from ..repo import ingest, workspace as ws
from . import runstore
from .context import Cancelled, SystemContext
from .orchestrator import run_orchestrator

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_REGISTRY: dict[str, dict[str, Any]] = {}
PERSISTABLE = {"explore_report", "plan", "test_report", "edits", "repairs", "metrics"}


class RunError(ValueError):
    """User-facing validation error (maps to HTTP 400)."""


# --------------------------------------------------------------------------- #
def create_run(repo_id: str, task: str, systems: list[str],
               settings: dict[str, Any]) -> dict[str, Any]:
    repo = ingest.get_repo(repo_id)
    if repo is None:
        raise RunError("repository not found")
    task = (task or "").strip()
    if not task:
        raise RunError("task must not be empty")
    systems = list(dict.fromkeys(systems))  # de-dupe, preserve order
    if not systems or any(s not in {"A", "B", "C"} for s in systems):
        raise RunError("systems must contain at least one of A, B, C")
    if set(systems) & {"B", "C"}:
        graph_status = graph_store.status(repo_id)
        if graph_status["status"] != "ready":
            raise RunError("Build the code knowledge graph before running "
                           "System B/C (Repository Workspace → Build Graph).")
    resolved = {
        "max_iterations": int(settings.get("max_iterations") or config.DEFAULT_MAX_ITERATIONS),
        "tool_call_budget": int(settings.get("tool_call_budget") or config.DEFAULT_TOOL_BUDGET),
        "token_budget": int(settings.get("token_budget") or config.DEFAULT_TOKEN_BUDGET),
        "timeout_sec": int(settings.get("timeout_sec") or config.DEFAULT_TIMEOUT_SEC),
        "model": settings.get("model") or None,
    }
    run_id = f"run_{uuid.uuid4().hex[:10]}"
    now = db.utcnow()
    db.insert("INSERT INTO runs (id, repo_id, task, systems, settings, status, created_at) "
              "VALUES (?,?,?,?,?,'queued',?)",
              (run_id, repo_id, task, json.dumps(systems), json.dumps(resolved), now))
    for system in systems:
        db.insert("INSERT INTO run_systems (run_id, system, status, metrics) "
                  "VALUES (?,?, 'pending', '{}')", (run_id, system))
    with _LOCK:
        _REGISTRY[run_id] = {"cancel": threading.Event(), "isolation": "local"}
    thread = threading.Thread(target=_execute_run, args=(run_id,), daemon=True,
                              name=f"{run_id}/master")
    thread.start()
    detail = runstore.run_detail(run_id)
    assert detail is not None
    return detail


def cancel_run(run_id: str) -> bool:
    with _LOCK:
        entry = _REGISTRY.get(run_id)
    if entry is None:
        return False
    entry["cancel"].set()
    runstore.emit_event(run_id, None, "log",
                        {"level": "warn", "message": "Cancellation requested"})
    return True


# --------------------------------------------------------------------------- #
def _make_persist(run_id: str, system: str):
    def _persist(key: str, value: Any) -> None:
        if key not in PERSISTABLE or value is None:
            return
        db.execute(f"UPDATE run_systems SET {key}=? WHERE run_id=? AND system=?",
                   (json.dumps(value, ensure_ascii=False, default=str), run_id, system))
    return _persist


def _derive_completion(ctx: SystemContext) -> str:
    report = ctx.test_report or {}
    try:
        passed, failed = int(report.get("passed") or 0), int(report.get("failed") or 0)
    except (TypeError, ValueError):
        passed, failed = 0, 0
    if ctx.completion in {"success", "failed"}:
        return ctx.completion
    if failed > 0:
        return "failed"
    if passed == 0:
        return "partial"
    return "success" if ctx.edits else "partial"


def _execute_run(run_id: str) -> None:
    run = runstore.get_run(run_id)
    if run is None:
        return
    db.execute("UPDATE runs SET status='running', started_at=? WHERE id=?",
               (db.utcnow(), run_id))
    runstore.emit_event(run_id, None, "run_started",
                        {"task": run["task"], "systems": run["systems"]})
    try:
        isolation = ws.resolve_isolation()
    except Exception:  # pragma: no cover - defensive
        logger.exception("isolation resolution failed; defaulting to local")
        isolation = "local"
    with _LOCK:
        _REGISTRY.setdefault(run_id, {})["isolation"] = isolation

    threads: list[threading.Thread] = []
    for system in run["systems"] or []:
        thread = threading.Thread(target=_run_system_safe, args=(run_id, system),
                                  daemon=True, name=f"{run_id}/{system}")
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()

    rows = runstore.get_run_systems(run_id)
    statuses = [row["status"] for row in rows]
    if statuses and all(s == "cancelled" for s in statuses):
        final = "cancelled"
    elif "failed" in statuses:
        final = "failed"
    elif "cancelled" in statuses:
        final = "cancelled"
    else:
        final = "completed"
    db.execute("UPDATE runs SET status=?, finished_at=? WHERE id=?",
               (final, db.utcnow(), run_id))
    runstore.emit_event(run_id, None, "run_finished", {"status": final})
    with _LOCK:
        _REGISTRY.pop(run_id, None)


def _run_system_safe(run_id: str, system: str) -> None:
    try:
        _run_system(run_id, system)
    except Exception as exc:  # last-resort guard: never leave a system 'running'
        logger.exception("system %s of %s crashed", system, run_id)
        message = f"{type(exc).__name__}: {exc}"[:800]
        try:
            runstore.emit_event(run_id, system, "error", {"message": message})
            db.execute(
                "UPDATE run_systems SET status='failed', error=?, finished_at=? "
                "WHERE run_id=? AND system=?",
                (message, db.utcnow(), run_id, system))
        except Exception:
            logger.exception("failed to record crash for %s/%s", run_id, system)


def _run_system(run_id: str, system: str) -> None:
    run = runstore.get_run(run_id)
    if run is None:
        raise RuntimeError(f"run {run_id} disappeared")
    repo = ingest.get_repo(run["repo_id"])
    if repo is None:
        raise RuntimeError(f"repository {run['repo_id']} disappeared")
    settings = run.get("settings") or {}
    with _LOCK:
        isolation = _REGISTRY.get(run_id, {}).get("isolation", "local")
        cancel = _REGISTRY.get(run_id, {}).get("cancel") or threading.Event()

    workspace = ws.create_workspace(run_id, system, repo["local_path"])
    exec_env = ws.ExecutionEnv(workspace=workspace, mode=isolation)

    graph = None
    if system in {"B", "C"}:
        loaded = graph_store.load(repo["id"])
        graph = loaded[0] if loaded else None

    llm = get_llm(settings.get("model"))

    def emit(etype: str, payload: dict[str, Any], stage: Optional[str] = None,
             agent: Optional[str] = None) -> None:
        runstore.emit_event(run_id, system, etype, payload, stage, agent)

    db.execute("UPDATE run_systems SET status='running', started_at=?, workspace=? "
               "WHERE run_id=? AND system=?",
               (db.utcnow(), str(workspace), run_id, system))
    emit("system_started", {"isolation": isolation, "workspace": str(workspace)})

    ctx = SystemContext(
        run_id=run_id, system=system, task=run["task"], repo=repo, workspace=workspace,
        exec_env=exec_env, llm=llm, model=settings.get("model") or getattr(llm, "model", ""),
        graph=graph, settings=settings, emit=emit, persist=_make_persist(run_id, system),
        cancel=cancel)

    status = "completed"
    error: Optional[str] = None
    try:
        run_orchestrator(ctx)
        entry = task_catalog.find_task(run["task"])
        report = ctx.test_report or {}
        try:
            passed = int(report.get("passed") or 0)
            failed = int(report.get("failed") or 0)
        except (TypeError, ValueError):
            passed = failed = 0
        if entry and entry.get("hidden_tests_dir") and failed == 0 and passed > 0:
            hidden = evaluate.evaluate_hidden(ctx, entry)
            if hidden:
                evaluate.apply_hidden_result(ctx, hidden)
        ctx.completion = _derive_completion(ctx)
    except Cancelled:
        status = "cancelled"
        emit("log", {"level": "warn", "message": "Execution cancelled by user"})
        ctx.completion = _derive_completion(ctx)
    except BudgetExceeded as exc:
        status = "completed"
        emit("budget_exceeded", {"budget": exc.budget})
        emit("log", {"level": "warn",
                     "message": f"{exc.budget} budget reached; terminating system"})
        ctx.completion = _derive_completion(ctx)
    except Exception as exc:
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"[:800]
        emit("error", {"message": error, "stage": ctx.stage})
        ctx.completion = _derive_completion(ctx)
    finally:
        try:
            ctx.save_artifacts()
            final_metrics = ctx.refresh_metrics()
            emit("system_finished", {"status": status, "completion": ctx.completion,
                                     "duration_ms": final_metrics["duration_ms"]})
            emit("metric_update", final_metrics, ctx.stage, "orchestrator")
            db.execute(
                "UPDATE run_systems SET status=?, finished_at=?, error=?, stage=?, "
                "current_agent=?, metrics=? WHERE run_id=? AND system=?",
                (status, db.utcnow(), error, ctx.stage or None, ctx.agent or None,
                 json.dumps(final_metrics, default=str), run_id, system))
        except Exception:
            logger.exception("finalization failed for %s/%s", run_id, system)
            db.execute("UPDATE run_systems SET status=?, finished_at=?, error=? "
                       "WHERE run_id=? AND system=?",
                       (status, db.utcnow(), error or "finalization failed",
                        run_id, system))
