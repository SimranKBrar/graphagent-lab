"""Persist and load the code knowledge graph (JSON node-link files)."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Optional

import networkx as nx

from .. import db, config

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, nx.MultiDiGraph, dict[str, Any]]] = {}


def graph_path(repo_id: str) -> Path:
    return config.GRAPHS_DIR / f"{repo_id}.json"


def mark_building(repo_id: str) -> None:
    db.execute("UPDATE repositories SET graph_status='building', graph_error=NULL WHERE id=?",
               (repo_id,))


def mark_error(repo_id: str, message: str) -> None:
    db.execute("UPDATE repositories SET graph_status='error', graph_error=? WHERE id=?",
               (message[:800], repo_id))


def status(repo_id: str) -> dict[str, Any]:
    row = db.query_one("SELECT graph_status, graph_error, graph_built_at FROM repositories WHERE id=?",
                       (repo_id,))
    if row is None:
        return {"status": "absent", "error": "repository not found"}
    stored = row["graph_status"]
    exists = graph_path(repo_id).exists()
    if stored == "ready" and not exists:
        stored = "absent"
    return {"status": stored, "error": row["graph_error"], "built_at": row["graph_built_at"]}


def save(repo_id: str, graph: nx.MultiDiGraph, stats: dict[str, Any]) -> None:
    nodes = [dict(data, id=node_id) for node_id, data in graph.nodes(data=True)]
    edges = []
    for src, dst, data in graph.edges(data=True):
        edge = dict(data)
        edge.setdefault("id", "")
        edge["source"] = src
        edge["target"] = dst
        edges.append(edge)
    payload = {"nodes": nodes, "edges": edges, "stats": stats}
    path = graph_path(repo_id)
    with _LOCK:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        _CACHE.pop(repo_id, None)
    built_at = db.utcnow()
    db.execute("UPDATE repositories SET graph_status='ready', graph_error=NULL, "
               "graph_built_at=? WHERE id=?", (built_at, repo_id))


def load(repo_id: str) -> Optional[tuple[nx.MultiDiGraph, dict[str, Any]]]:
    path = graph_path(repo_id)
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    with _LOCK:
        cached = _CACHE.get(repo_id)
        if cached is not None and cached[0] == mtime:
            return cached[1], cached[2]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    graph = nx.MultiDiGraph()
    for node in payload.get("nodes", []):
        graph.add_node(node["id"], **{k: v for k, v in node.items() if k != "id"})
    for edge in payload.get("edges", []):
        src, dst = edge.get("source"), edge.get("target")
        if src is None or dst is None or src not in graph or dst not in graph:
            continue
        graph.add_edge(src, dst, **{k: v for k, v in edge.items()
                                    if k not in {"source", "target"}})
    stats = payload.get("stats", {})
    with _LOCK:
        _CACHE[repo_id] = (mtime, graph, stats)
    return graph, stats


def require(repo_id: str) -> tuple[nx.MultiDiGraph, dict[str, Any]]:
    loaded = load(repo_id)
    if loaded is None:
        raise KeyError(f"graph not built for {repo_id}")
    return loaded
