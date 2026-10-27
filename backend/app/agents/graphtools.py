"""Code-knowledge-graph and GNN tools (Systems B and C only).

Every graph tool call emits a `graph_visit` event so the Graph Explorer can
replay exactly which nodes each agent touched.
"""
from __future__ import annotations

from typing import Any

from ..graph import tools as graph_tools
from ..gnn import stub as gnn_stub
from .filetools import Tool


def build_graph_tools(ctx) -> list[Tool]:
    if ctx.graph is None:
        return []

    def graph_search(args: dict) -> dict:
        query = str(args.get("query") or "")
        limit = min(50, int(args.get("limit") or 20))
        results = graph_tools.search(ctx.graph, query, limit=limit)
        ctx.on_graph_visit([r["id"] for r in results], f"search '{query}'")
        return {"query": query, "results": results, "count": len(results)}

    def graph_neighbors(args: dict) -> dict:
        node_id = str(args.get("node_id") or "")
        direction = str(args.get("direction") or "both")
        edge_types = args.get("edge_types") or None
        if isinstance(edge_types, list):
            edge_types = [str(t) for t in edge_types]
        limit = min(80, int(args.get("limit") or 40))
        neighbors = graph_tools.neighbors(ctx.graph, node_id, direction=direction,
                                          edge_types=edge_types, limit=limit)
        ctx.on_graph_visit([node_id] + [n["id"] for n in neighbors],
                           f"neighbors of {node_id}")
        return {"node_id": node_id, "direction": direction,
                "neighbors": neighbors, "count": len(neighbors)}

    def graph_impact(args: dict) -> dict:
        node_id = str(args.get("node_id") or "")
        depth = min(5, max(1, int(args.get("depth") or 3)))
        result = graph_tools.impact(ctx.graph, node_id, depth=depth)
        ids = [n["id"] for n in result.get("affected", [])]
        if result.get("node"):
            ids.append(result["node"]["id"])
        ctx.on_graph_visit(ids, f"impact analysis of {node_id}")
        return result

    def graph_summary(args: dict) -> dict:
        summary = graph_tools.summary(ctx.graph)
        return summary

    return [
        Tool("graph_search", "Search the code knowledge graph for functions, classes and "
                             "modules by name/qualname/file.",
             {"query": {"type": "string"},
              "limit": {"type": "integer", "description": "max results (default 20)"}},
             graph_search, required=["query"]),
        Tool("graph_neighbors", "Traverse direct dependencies of a graph node: callers, "
                                "callees, imports, inheritance, and test links.",
             {"node_id": {"type": "string", "description": "e.g. orders/service.py::create_order"},
              "direction": {"type": "string", "enum": ["in", "out", "both"],
                            "description": "default both"},
              "edge_types": {"type": "array", "items": {"type": "string"},
                             "description": "filter: calls, imports, inherits, defines, tests"},
              "limit": {"type": "integer"}},
             graph_neighbors, required=["node_id"]),
        Tool("graph_impact", "Change-impact analysis: which components depend on this node "
                             "(upstream, affected) and what it depends on (downstream).",
             {"node_id": {"type": "string"},
              "depth": {"type": "integer", "description": "traversal depth (default 3, max 5)"}},
             graph_impact, required=["node_id"]),
        Tool("graph_summary", "Counts of graph nodes/edges by kind and relationship type.",
             {}, graph_summary),
    ]


def build_gnn_tools(ctx) -> list[Tool]:
    if ctx.graph is None:
        return []

    def gnn_relevance(args: dict) -> dict:
        task = str(args.get("task") or ctx.task)
        top_k = min(40, max(1, int(args.get("top_k") or 15)))
        result = gnn_stub.predict_relevance(ctx.graph, task, top_k=top_k)
        ids = [p["node"]["id"] for p in result["predictions"] if p.get("node")]
        ctx.on_graph_visit(ids, "GNN relevance predictions")
        return result

    def gnn_impact(args: dict) -> dict:
        node_id = str(args.get("node_id") or "")
        top_k = min(40, max(1, int(args.get("top_k") or 15)))
        result = gnn_stub.predict_impact(ctx.graph, node_id=node_id, top_k=top_k)
        ids = [p["node"]["id"] for p in result["predictions"] if p.get("node")]
        if result.get("node"):
            ids.append(result["node"]["id"])
        ctx.on_graph_visit(ids, "GNN impact predictions")
        return result

    return [
        Tool("gnn_relevance", "GNN (or Phase-3 placeholder heuristic) ranking of functions "
                              "and classes by predicted relevance to the task.",
             {"task": {"type": "string", "description": "defaults to the current task"},
              "top_k": {"type": "integer", "description": "default 15"}},
             gnn_relevance),
        Tool("gnn_impact", "Predicted change-impact ranking: components likely affected by "
                           "modifying a node (or the whole repo when node_id omitted).",
             {"node_id": {"type": "string", "description": "optional focus node"},
              "top_k": {"type": "integer"}},
             gnn_impact),
    ]
