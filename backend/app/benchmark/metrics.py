"""Cross-run aggregation for the Benchmark Dashboard (Phase-4 scaffold)."""
from __future__ import annotations

from typing import Any

from .. import db

AVERAGE_FIELDS = {
    "tests_passed": "tests_passed",
    "tokens": "tokens",
    "cost_usd": "cost_usd",
    "duration_ms": "duration_ms",
    "tool_calls": "tool_calls",
    "repairs": "repairs",
    "files_modified": "files_modified",
    "graph_queries": "graph_queries",
}


def _empty_agg() -> dict[str, Any]:
    return {"runs": 0, "successes": 0, "completion_rate": 0.0,
            **{f"avg_{key}": 0.0 for key in AVERAGE_FIELDS}}


def aggregate() -> dict[str, Any]:
    runs = db.query("SELECT * FROM runs ORDER BY created_at DESC LIMIT 200")
    agg: dict[str, dict[str, Any]] = {"A": _empty_agg(), "B": _empty_agg(), "C": _empty_agg()}
    run_out: list[dict[str, Any]] = []
    totals: dict[str, dict[str, list[float]]] = {
        s: {key: [] for key in AVERAGE_FIELDS} for s in ("A", "B", "C")}

    for run in runs:
        try:
            import json
            systems = json.loads(run["systems"])
        except ValueError:
            continue
        rows = db.query("SELECT * FROM run_systems WHERE run_id=?", (run["id"],))
        by_system: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                metrics = json.loads(row["metrics"] or "{}")
            except ValueError:
                metrics = {}
            completion = metrics.get("completion", "pending")
            system = row["system"]
            by_system[system] = {**metrics, "completion": completion,
                                 "status": row["status"]}
            if system in totals:
                agg[system]["runs"] += 1
                if completion == "success":
                    agg[system]["successes"] += 1
                for field in AVERAGE_FIELDS:
                    value = metrics.get(field)
                    if isinstance(value, (int, float)):
                        totals[system][field].append(float(value))
        if systems:
            run_out.append({
                "run_id": run["id"], "task": run["task"], "created_at": run["created_at"],
                "status": run["status"], "systems": by_system,
            })

    for system, fields in totals.items():
        if agg[system]["runs"]:
            agg[system]["completion_rate"] = round(
                agg[system]["successes"] / agg[system]["runs"], 3)
        for field, values in fields.items():
            if values:
                agg[system][f"avg_{field}"] = round(sum(values) / len(values), 3)

    return {"aggregates": agg, "runs": run_out}
