"""Event log writes and run/run-system query helpers (read side of the API)."""
from __future__ import annotations

import json
from typing import Any, Optional

from .. import db

JSON_FIELDS_SYSTEM = ("metrics", "explore_report", "plan", "test_report", "edits", "repairs")

SYSTEM_NAMES = {"A": "Standard", "B": "Graph-Augmented", "C": "GNN-Enhanced"}


def emit_event(run_id: str, system: Optional[str], etype: str, payload: dict[str, Any],
               stage: Optional[str] = None, agent: Optional[str] = None) -> dict[str, Any]:
    """Insert an event; live side effects mirror it into run_systems columns."""
    if etype == "metric_update" and system:
        db.execute("UPDATE run_systems SET metrics=? WHERE run_id=? AND system=?",
                   (json.dumps(payload), run_id, system))
    elif etype == "stage_started" and system:
        db.execute("UPDATE run_systems SET stage=?, current_agent=? WHERE run_id=? AND system=?",
                   (payload.get("stage"), agent, run_id, system))
    seq = db.insert(
        "INSERT INTO events (run_id, ts, system, type, stage, agent, payload) "
        "VALUES (?,?,?,?,?,?,?)",
        (run_id, db.utcnow(), system, etype, stage, agent, json.dumps(payload, default=str)))
    return {"seq": seq, "ts": db.utcnow(), "system": system, "type": etype,
            "stage": stage, "agent": agent, "payload": payload}


def get_events(run_id: str, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT id, ts, system, type, stage, agent, payload FROM events "
        "WHERE run_id=? AND id>? ORDER BY id ASC LIMIT ?",
        (run_id, after, limit))
    events = []
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except (ValueError, TypeError):
            payload = {}
        events.append({"seq": row["id"], "ts": row["ts"], "system": row["system"],
                       "type": row["type"], "stage": row["stage"],
                       "agent": row["agent"], "payload": payload})
    return events


def latest_seq(run_id: str) -> int:
    row = db.query_one("SELECT MAX(id) AS m FROM events WHERE run_id=?", (run_id,))
    return int(row["m"] or 0) if row else 0


# --------------------------------------------------------------------------- #
def get_run(run_id: str) -> Optional[dict[str, Any]]:
    row = db.query_one("SELECT * FROM runs WHERE id=?", (run_id,))
    return db.row_to_dict(row, json_fields=("systems", "settings")) if row else None


def get_run_systems(run_id: str) -> list[dict[str, Any]]:
    rows = db.query("SELECT * FROM run_systems WHERE run_id=? ORDER BY system", (run_id,))
    return [db.row_to_dict(r, json_fields=JSON_FIELDS_SYSTEM) for r in rows]  # type: ignore[misc]


def list_runs(limit: int = 100) -> list[dict[str, Any]]:
    rows = db.query("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,))
    out = []
    for row in rows:
        run = db.row_to_dict(row, json_fields=("systems", "settings"))
        if run:
            repo = db.query_one("SELECT name FROM repositories WHERE id=?", (run["repo_id"],))
            run["repo_name"] = repo["name"] if repo else None
            out.append(run)
    return out


def run_summary(run: dict[str, Any]) -> dict[str, Any]:
    return {key: run.get(key) for key in
            ("id", "repo_id", "task", "systems", "status", "created_at", "finished_at")} | \
           {"repo_name": run.get("repo_name")}


def _system_out(system_row: dict[str, Any]) -> dict[str, Any]:
    metrics = system_row.get("metrics") or {}
    return {
        "system": system_row["system"],
        "status": system_row.get("status") or "pending",
        "stage": system_row.get("stage"),
        "current_agent": system_row.get("current_agent"),
        "started_at": system_row.get("started_at"),
        "finished_at": system_row.get("finished_at"),
        "error": system_row.get("error"),
        "metrics": metrics,
        "completion": metrics.get("completion", "pending"),
        "plan": system_row.get("plan"),
        "test_report": system_row.get("test_report"),
    }


def run_detail(run_id: str) -> Optional[dict[str, Any]]:
    run = get_run(run_id)
    if run is None:
        return None
    repo = db.query_one("SELECT name FROM repositories WHERE id=?", (run["repo_id"],))
    summary = run_summary(run | {"repo_name": repo["name"] if repo else None})
    systems = [_system_out(s) for s in get_run_systems(run_id)]
    return summary | {"settings": run.get("settings") or {}, "systems": systems}


def system_detail(run_id: str, system: str) -> Optional[dict[str, Any]]:
    row = db.query_one("SELECT * FROM run_systems WHERE run_id=? AND system=?",
                       (run_id, system))
    if row is None:
        return None
    data = db.row_to_dict(row, json_fields=JSON_FIELDS_SYSTEM)
    assert data is not None
    metrics = data.get("metrics") or {}
    return {
        "system": system,
        "status": data.get("status"),
        "stage": data.get("stage"),
        "metrics": metrics,
        "completion": metrics.get("completion", "pending"),
        "explore_report": data.get("explore_report"),
        "plan": data.get("plan"),
        "edits": data.get("edits") or [],
        "test_report": data.get("test_report"),
        "repairs": data.get("repairs") or [],
        "workspace": data.get("workspace"),
        "error": data.get("error"),
    }
