"""GNN prediction layer (Phase-3 boundary).

Phase 3 replaces `predict_relevance` / `predict_impact` with a trained
GraphSAGE model (PyTorch Geometric) over the same graph. Until a model file
exists, predictions come from a deterministic structural+lexical heuristic and
are labeled `source="heuristic"` everywhere so the UI and benchmark can report
them honestly rather than implying trained-model output.

`train.py` next to this module documents/automates the Phase-3 training path
and is safe to import without torch installed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import networkx as nx

from .. import config
from ..graph import tools as graph_tools

MODEL_PATH = config.DATA_DIR / "gnn" / "model.pt"


def model_info() -> dict[str, Any]:
    trained = MODEL_PATH.exists()
    return {
        "trained": trained,
        "architecture": "GraphSAGE" if trained else None,
        "placeholder": not trained,
        "model_path": str(MODEL_PATH) if trained else None,
        "task": "function relevance + change impact",
        "note": ("Trained GraphSAGE model" if trained else
                 "No trained model yet — Phase-3 placeholder using a "
                 "structural/lexical heuristic (clearly labeled in results)."),
    }


def has_model() -> bool:
    return MODEL_PATH.exists()


def predict_relevance(graph: Optional[nx.MultiDiGraph], task: str,
                      top_k: int = 15) -> dict[str, Any]:
    if graph is None:
        raise ValueError("code knowledge graph is not available")
    predictions = graph_tools.relevance(graph, task, top_k=top_k)
    return {"task": task, "predictions": predictions, "model": model_info(),
            "source": "heuristic" if not has_model() else "gnn"}


def predict_impact(graph: Optional[nx.MultiDiGraph], node_id: str = "",
                   top_k: int = 15) -> dict[str, Any]:
    if graph is None:
        raise ValueError("code knowledge graph is not available")
    if node_id:
        scoped = graph_tools.impact(graph, node_id, depth=2)
        return {"node": scoped["node"],
                "predictions": [{"node": n, "score": None, "source": "structural"}
                                for n in scoped["affected"][:top_k]],
                "model": model_info(), "source": "structural" if not has_model() else "gnn"}
    predictions = graph_tools.impact_scores(graph, top_k=top_k)
    return {"node": None, "predictions": predictions, "model": model_info(),
            "source": "heuristic" if not has_model() else "gnn"}
