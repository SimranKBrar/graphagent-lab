"""Competing system definitions: identical tools except graph (B) and GNN (C).

System A — Standard:            file/terminal tools
System B — Graph-Augmented:     + code knowledge graph traversal tools
System C — GNN-Enhanced:        + graph tools + GNN prediction tools
"""
from __future__ import annotations

from .filetools import Tool, build_file_tools
from .graphtools import build_gnn_tools, build_graph_tools

SYSTEM_LABELS = {
    "A": "System A · Standard Multi-Agent LLM",
    "B": "System B · Graph-Augmented Multi-Agent LLM",
    "C": "System C · GNN-Enhanced Multi-Agent LLM",
}

# Per-stage file-tool access (graph/gnn tools are read-only and always allowed
# for B/C wherever present).
_STAGE_FILE_TOOLS = {
    "explore": {"list_dir", "read_file", "grep"},
    "plan": {"list_dir", "read_file", "grep"},
    "edit": {"list_dir", "read_file", "grep", "write_file"},
    "test": {"list_dir", "read_file", "grep", "run_tests", "run_command"},
    "repair": {"list_dir", "read_file", "grep", "write_file", "run_tests", "run_command"},
}


def build_tools(ctx, stage: str) -> list[Tool]:
    allowed = _STAGE_FILE_TOOLS.get(stage, {t.name for t in build_file_tools(ctx)})
    tools = [t for t in build_file_tools(ctx) if t.name in allowed]
    if ctx.system in {"B", "C"}:
        tools += build_graph_tools(ctx)
    if ctx.system == "C":
        tools += build_gnn_tools(ctx)
    return tools
