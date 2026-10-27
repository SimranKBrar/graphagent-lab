"""Hidden-test evaluation: the independent success criterion (Phase-4 core).

Hidden tests live under `examples/hidden_tests/` and are never present in the
agent's workspace. After a system finishes with a passing visible suite, the
relevant hidden tests are copied in as `tests_hidden/` and executed; results
adjust the system's completion verdict and are reported as a `test_results`
event with `hidden: true`.
"""
from __future__ import annotations

import shutil
from typing import Any, Optional

from .. import config
from ..agents.testparse import parse_pytest


def evaluate_hidden(ctx, task_entry: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Run the task's hidden tests in the system workspace. Returns the parsed
    report, or None when the task has no hidden tests configured."""
    if not task_entry or not task_entry.get("hidden_tests_dir"):
        return None
    src = config.EXAMPLES_DIR / str(task_entry["hidden_tests_dir"])
    if not src.is_dir():
        return None
    dest = ctx.workspace / "tests_hidden"
    try:
        shutil.copytree(src, dest, dirs_exist_ok=True)
    except OSError:
        return None
    result = ctx.exec_env.run_argv(
        ["python", "-m", "pytest", "-q", "--tb=short", "-rf", "tests_hidden"],
        timeout=config.TEST_TIMEOUT_SEC)
    parsed = parse_pytest(result.combined, result.exit_code)
    parsed.update({"command": "pytest -q tests_hidden", "hidden": True,
                   "output": result.combined[-6000:], "ok": parsed["failed"] == 0})
    return parsed


def apply_hidden_result(ctx, hidden: dict[str, Any]) -> str:
    """Record hidden metrics/events and adjust the completion verdict.

    Returns the (possibly updated) completion value.
    """
    passed = int(hidden.get("passed") or 0)
    failed = int(hidden.get("failed") or 0)
    ctx.emit("test_results", {
        "passed": passed, "failed": failed,
        "failures": hidden.get("failures") or [],
        "summary": str(hidden.get("summary") or "hidden tests"),
        "hidden": True,
    }, "done", "evaluator")
    ctx.hidden = {"passed": passed, "failed": failed}
    if failed > 0:
        ctx.completion = "failed"
    elif passed > 0 and ctx.completion in {"success", "partial"}:
        ctx.completion = "success"
    metrics = ctx.refresh_metrics()
    ctx.emit("metric_update", dict(metrics), "done", "evaluator")
    return ctx.completion
