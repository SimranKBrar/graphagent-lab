"""SQLite persistence: repositories, runs, run systems, and the event log.

A single shared connection guarded by an RLock is sufficient for the lab's
concurrency profile (a handful of worker threads plus the API process).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from . import config

_LOCK = threading.RLock()
_CONN: Optional[sqlite3.Connection] = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS repositories (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  source_type TEXT NOT NULL,
  origin_url TEXT,
  local_path TEXT NOT NULL,
  default_branch TEXT,
  commit_sha TEXT,
  file_count INTEGER DEFAULT 0,
  total_bytes INTEGER DEFAULT 0,
  languages TEXT DEFAULT '{}',
  graph_status TEXT DEFAULT 'absent',
  graph_error TEXT,
  graph_built_at TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL,
  task TEXT NOT NULL,
  systems TEXT NOT NULL,
  settings TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  FOREIGN KEY (repo_id) REFERENCES repositories(id)
);

CREATE TABLE IF NOT EXISTS run_systems (
  run_id TEXT NOT NULL,
  system TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  stage TEXT,
  current_agent TEXT,
  error TEXT,
  metrics TEXT DEFAULT '{}',
  explore_report TEXT,
  plan TEXT,
  test_report TEXT,
  edits TEXT DEFAULT '[]',
  repairs TEXT DEFAULT '[]',
  workspace TEXT,
  started_at TEXT,
  finished_at TEXT,
  PRIMARY KEY (run_id, system)
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  system TEXT,
  type TEXT NOT NULL,
  stage TEXT,
  agent TEXT,
  payload TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, id);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def connect() -> sqlite3.Connection:
    global _CONN
    with _LOCK:
        if _CONN is None:
            config.ensure_dirs()
            _CONN = sqlite3.connect(str(config.DB_PATH), check_same_thread=False)
            _CONN.row_factory = sqlite3.Row
            _CONN.executescript(SCHEMA)
            _CONN.commit()
        return _CONN


def query(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    with _LOCK:
        return connect().execute(sql, tuple(params)).fetchall()


def query_one(sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    with _LOCK:
        conn = connect()
        cur = conn.execute(sql, tuple(params))
        conn.commit()
        return cur.rowcount


def insert(sql: str, params: Iterable[Any] = ()) -> int:
    with _LOCK:
        conn = connect()
        cur = conn.execute(sql, tuple(params))
        conn.commit()
        return cur.lastrowid


def row_to_dict(row: Optional[sqlite3.Row], json_fields: Iterable[str] = ()) -> Optional[dict]:
    if row is None:
        return None
    data = dict(row)
    for field in json_fields:
        raw = data.get(field)
        if isinstance(raw, str):
            try:
                data[field] = json.loads(raw)
            except (ValueError, TypeError):
                data[field] = None
    return data
