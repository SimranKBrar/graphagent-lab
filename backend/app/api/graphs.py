"""Code knowledge graph endpoints: build, data, search, node detail, subgraph."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from .. import db
from ..gnn import stub as gnn_stub
from ..graph import builder, store, tools as graph_tools
from ..repo import ingest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["graph"])

_BUILDING: set[str] = set()


def _require_repo(repo_id: str) -> dict:
    repo = ingest.get_repo(repo_id)
    if repo is None:
        raise HTTPException(404, detail="repository not found")
    return repo


def _require_graph(repo_id: str):
    try:
        graph, stats = store.require(repo_id)
    except KeyError as exc:
        raise HTTPException(404, detail="code knowledge graph has not been built yet") from exc
    return graph, stats


def _with_scores(nodes: list[dict]) -> list[dict]:
    """Attach GNN score fields (null until a trained model exists, per contract)."""
    trained = gnn_stub.has_model()
    out = []
    for node in nodes:
        item = dict(node)
        item.setdefault("gnn_score", None)
        item.setdefault("gnn_impact", None)
        if trained and node.get("kind") not in {"module"}:
            item["gnn_score"] = node.get("gnn_score")
        out.append(item)
    return out


def _node_link(graph, stats: dict) -> dict:
    nodes = _with_scores([dict(data, id=node_id) for node_id, data in graph.nodes(data=True)])
    edges = []
    for src, dst, data in graph.edges(data=True):
        edge = dict(data)
        edge.setdefault("id", "")
        edge["source"] = src
        edge["target"] = dst
        edges.append(edge)
    return {"nodes": nodes, "edges": edges, "stats": stats}


@router.get("/repos/{repo_id}/graph")
def graph_status(repo_id: str):
    _require_repo(repo_id)
    status = store.status(repo_id)
    stats = None
    if status["status"] == "ready":
        loaded = store.load(repo_id)
        if loaded:
            stats = loaded[1]
    return {"status": status["status"], "stats": stats,
            "error": status.get("error")}


@router.post("/repos/{repo_id}/graph")
def build_graph(repo_id: str):
    repo = _require_repo(repo_id)
    status = store.status(repo_id)
    if status["status"] == "building" or repo_id in _BUILDING:
        return {"status": "building"}
    store.mark_building(repo_id)
    _BUILDING.add(repo_id)

    def worker():
        try:
            graph, stats = builder.build_graph(Path(repo["local_path"]))
            store.save(repo_id, graph, stats)
        except Exception as exc:
            logger.exception("graph build failed for %s", repo_id)
            store.mark_error(repo_id, f"{type(exc).__name__}: {exc}")
        finally:
            _BUILDING.discard(repo_id)

    threading.Thread(target=worker, daemon=True, name=f"graph-{repo_id}").start()
    return {"status": "building"}


@router.get("/repos/{repo_id}/graph/data")
def graph_data(repo_id: str):
    _require_repo(repo_id)
    graph, stats = _require_graph(repo_id)
    return _node_link(graph, stats)


@router.get("/repos/{repo_id}/graph/search")
def graph_search(repo_id: str, q: str = Query(""), limit: int = 50):
    _require_repo(repo_id)
    graph, _ = _require_graph(repo_id)
    return graph_tools.search(graph, q, limit=min(limit, 100))


@router.get("/repos/{repo_id}/graph/node")
def graph_node(repo_id: str, node_id: str):
    _require_repo(repo_id)
    graph, _ = _require_graph(repo_id)
    detail = graph_tools.node_detail(graph, node_id)
    if detail is None:
        raise HTTPException(404, detail=f"node not found: {node_id}")
    node = detail["node"]
    source = None
    repo = ingest.get_repo(repo_id)
    if repo:
        try:
            target = Path(repo["local_path"]) / node.get("file", "")
            if target.is_file():
                lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
                if node.get("kind") == "module":
                    source = "\n".join(lines[:400])
                else:
                    start = max(0, int(node.get("line") or 1) - 1)
                    end = min(len(lines), int(node.get("end_line") or start + 200))
                    source = "\n".join(lines[start:end])
        except OSError:
            source = None
    gnn_score = None
    gnn_impact = None
    if gnn_stub.has_model() and node.get("kind") != "module":
        prediction = gnn_stub.predict_relevance(graph, str(node.get("label") or ""), top_k=5)
        for item in prediction["predictions"]:
            if item["node"]["id"] == node_id:
                gnn_score = item["score"]
    node = dict(node, gnn_score=gnn_score, gnn_impact=gnn_impact)
    return {**detail, "node": node, "source": source}


@router.get("/repos/{repo_id}/graph/subgraph")
def graph_subgraph(repo_id: str, center: str, depth: int = 2):
    _require_repo(repo_id)
    graph, stats = _require_graph(repo_id)
    data = graph_tools.subgraph(graph, center, depth=min(depth, 5))
    return {**_node_link(graph, stats), **data}
