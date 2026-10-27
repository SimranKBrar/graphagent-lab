"""Read-only query helpers over the code knowledge graph.

Pure functions over a NetworkX MultiDiGraph. Used by the HTTP API and by the
agent tool layer (System B/C), which additionally logs `graph_visit` events.
"""
from __future__ import annotations

import re
from typing import Any, Optional

import networkx as nx

EDGE_TYPES = ("calls", "imports", "inherits", "defines", "tests")
WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _node_summary(graph: nx.MultiDiGraph, node_id: str) -> dict[str, Any]:
    data = graph.nodes[node_id]
    return {"id": node_id, "label": data.get("label", node_id), "kind": data.get("kind", "?"),
            "file": data.get("file"), "line": data.get("line"), "test": bool(data.get("test"))}


def search(graph: nx.MultiDiGraph, query: str, limit: int = 50) -> list[dict[str, Any]]:
    q = query.lower().strip()
    if not q:
        return []
    scored: list[tuple[int, dict[str, Any]]] = []
    for node_id, data in graph.nodes(data=True):
        label = str(data.get("label", "")).lower()
        qual = str(data.get("qualname", "")).lower()
        path = str(data.get("file", "")).lower()
        if q in label:
            score = 0 if label == q else (1 if label.startswith(q) else 2)
        elif q in qual:
            score = 3
        elif q in path:
            score = 4
        else:
            continue
        scored.append((score, _node_summary(graph, node_id)))
    scored.sort(key=lambda pair: (pair[0], pair[1].get("label") or ""))
    return [item for _, item in scored[:limit]]


def neighbors(graph: nx.MultiDiGraph, node_id: str, direction: str = "both",
              edge_types: Optional[list[str]] = None, limit: int = 40) -> list[dict[str, Any]]:
    if node_id not in graph:
        return []
    allowed = set(edge_types or EDGE_TYPES)
    out: list[dict[str, Any]] = []
    if direction in {"out", "both"}:
        for _, dst, data in graph.out_edges(node_id, data=True):
            if data.get("type") in allowed:
                out.append({"direction": "out", "edge_type": data.get("type"),
                            **_node_summary(graph, dst)})
    if direction in {"in", "both"}:
        for src, _, data in graph.in_edges(node_id, data=True):
            if data.get("type") in allowed:
                out.append({"direction": "in", "edge_type": data.get("type"),
                            **_node_summary(graph, src)})
    return out[:limit]


def impact(graph: nx.MultiDiGraph, node_id: str, depth: int = 3) -> dict[str, Any]:
    """Who depends on this node (callers/imports up to `depth` hops) plus what
    it depends on. The basis of change-impact analysis."""
    if node_id not in graph:
        return {"node": None, "affected": [], "dependencies": []}
    affected: list[dict[str, Any]] = []
    frontier = [node_id]
    seen = {node_id}
    for _ in range(max(1, depth)):
        nxt: list[str] = []
        for current in frontier:
            for src, _, data in graph.in_edges(current, data=True):
                if data.get("type") in {"calls", "imports", "tests", "inherits"} and src not in seen:
                    seen.add(src)
                    nxt.append(src)
                    affected.append(_node_summary(graph, src))
        frontier = nxt
    deps: list[dict[str, Any]] = []
    frontier = [node_id]
    seen_deps = {node_id}
    for _ in range(max(1, depth)):
        nxt = []
        for current in frontier:
            for _, dst, data in graph.out_edges(current, data=True):
                if data.get("type") in {"calls", "imports", "tests", "inherits"} and dst not in seen_deps:
                    seen_deps.add(dst)
                    nxt.append(dst)
                    deps.append(_node_summary(graph, dst))
        frontier = nxt
    return {"node": _node_summary(graph, node_id), "affected": affected[:60],
            "dependencies": deps[:60]}


def node_detail(graph: nx.MultiDiGraph, node_id: str) -> Optional[dict[str, Any]]:
    if node_id not in graph:
        return None
    callers, callees, related = [], [], []
    for src, _, data in graph.in_edges(node_id, data=True):
        entry = {**_node_summary(graph, src), "line": data.get("line")}
        (callers if data.get("type") in {"calls", "tests"} else related).append(
            {**entry, "type": data.get("type")})
    for _, dst, data in graph.out_edges(node_id, data=True):
        entry = {**_node_summary(graph, dst), "line": data.get("line")}
        (callees if data.get("type") in {"calls", "tests"} else related).append(
            {**entry, "type": data.get("type")})
    return {"node": dict(graph.nodes[node_id], id=node_id),
            "callers": callers[:50], "callees": callees[:50], "related": related[:50]}


def subgraph(graph: nx.MultiDiGraph, center: str, depth: int = 2) -> dict[str, Any]:
    if center not in graph:
        return {"nodes": [], "edges": []}
    seen = {center}
    frontier = [center]
    for _ in range(max(0, depth)):
        nxt = []
        for current in frontier:
            for a, b in graph.edges(current):
                for other in (a, b):
                    if other not in seen:
                        seen.add(other)
                        nxt.append(other)
            for pred in graph.predecessors(current):
                if pred not in seen:
                    seen.add(pred)
                    nxt.append(pred)
        frontier = nxt
    nodes = [dict(graph.nodes[n], id=n) for n in seen]
    edges = [{"id": data.get("id", ""), "source": a, "target": b,
              **{k: v for k, v in data.items() if k != "id"}}
             for a, b, data in graph.edges(data=True) if a in seen and b in seen]
    return {"nodes": nodes, "edges": edges}


def summary(graph: nx.MultiDiGraph) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    for _, data in graph.nodes(data=True):
        key = str(data.get("kind", "?"))
        by_kind[key] = by_kind.get(key, 0) + 1
    by_edge: dict[str, int] = {}
    for _, _, data in graph.edges(data=True):
        key = str(data.get("type", "?"))
        by_edge[key] = by_edge.get(key, 0) + 1
    return {"nodes": graph.number_of_nodes(), "edges": graph.number_of_edges(),
            "by_kind": by_kind, "by_edge": by_edge}


def relevance(graph: nx.MultiDiGraph, task: str, top_k: int = 15) -> list[dict[str, Any]]:
    """Keyword-overlap relevance scoring.

    This is the Phase-3 placeholder: while no trained GNN model exists it ranks
    nodes with a deterministic structural+lexical heuristic and reports
    source="heuristic" so the UI can label results honestly.
    """
    words = {w.lower() for w in WORD_RE.findall(task) if len(w) > 2}
    words -= {"the", "and", "for", "with", "that", "this", "fix", "add", "bug", "when", "all"}
    if not words:
        return []
    ranked: list[tuple[float, dict[str, Any]]] = []
    degree = dict(graph.degree())
    for node_id, data in graph.nodes(data=True):
        if data.get("kind") == "module":
            continue
        label = str(data.get("label", "")).lower().replace("_", " ")
        qual = str(data.get("qualname", "")).lower().replace("_", " ")
        doc = str(data.get("doc", "")).lower()
        hit = sum(1 for w in words if w in label or w in qual)
        hit += sum(1 for w in words if w in doc) * 0.5
        if hit <= 0:
            continue
        cent = min(1.0, degree.get(node_id, 0) / 10.0)
        score = min(1.0, 0.12 * hit + 0.35 * cent + (0.15 if data.get("test") else 0.0))
        ranked.append((round(score, 4), _node_summary(graph, node_id)))
    ranked.sort(key=lambda pair: -pair[0])
    return [{"node": node, "score": score, "source": "heuristic"}
            for score, node in ranked[:top_k]]


def impact_scores(graph: nx.MultiDiGraph, top_k: int = 15) -> list[dict[str, Any]]:
    """Predicted change-impact magnitude per node (Phase-3 GNN placeholder)."""
    in_deg = {n: graph.in_degree(n) for n in graph.nodes()}
    ranked = sorted(in_deg.items(), key=lambda kv: -kv[1])[:top_k]
    max_deg = max((d for _, d in ranked), default=1) or 1
    return [{"node": _node_summary(graph, node_id), "score": round(d / max_deg, 4),
             "source": "heuristic"}
            for node_id, d in ranked if d > 0]
