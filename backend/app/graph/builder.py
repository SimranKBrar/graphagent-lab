"""Build the NetworkX code knowledge graph from parsed repository facts."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import networkx as nx

from . import parser

# Names never worth resolving as repository symbols.
BUILTIN_SKIP = {
    "print", "len", "range", "str", "int", "float", "bool", "list", "dict", "set", "tuple",
    "super", "isinstance", "issubclass", "getattr", "setattr", "hasattr", "open", "enumerate",
    "zip", "map", "filter", "sorted", "sum", "min", "max", "abs", "round", "type", "object",
    "Exception", "ValueError", "TypeError", "KeyError", "IndexError", "RuntimeError",
    "NotImplementedError", "AssertionError", "AttributeError", "StopIteration",
    "importlib", "append", "extend", "items", "keys", "values", "join", "format", "encode",
    "decode", "startswith", "endswith", "replace", "split", "strip", "lower", "upper", "copy",
    "deepcopy", "loads", "dumps", "time", "now", "utcnow", "call", "partial", "compile",
    "is_alive", "sleep", "exit", "main", "setup", "self", "cls", "require", "test",
}


def _module_name(rel_path: str) -> str:
    p = Path(rel_path)
    parts = list(p.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or p.stem


def _has_edge_type(graph: nx.MultiDiGraph, u: str, v: str, edge_type: str) -> bool:
    """True when a u->v edge of the given type already exists (MultiDiGraph-safe)."""
    data = graph.get_edge_data(u, v)
    if not data:
        return False
    return any(d.get("type") == edge_type for d in data.values())


def _module_index(root: Path) -> dict[str, str]:
    index: dict[str, str] = {}
    for abs_path in _iter_source_files(root):
        rel = str(abs_path.relative_to(root))
        if parser.should_skip(rel):
            continue
        index[_module_name(rel)] = rel
    return index


def _iter_source_files(root: Path):
    ignore = {".git", "__pycache__", "node_modules", ".venv", "venv", ".pytest_cache",
              ".mypy_cache", "dist", "build"}
    for path in sorted(root.rglob("*")):
        if any(part in ignore or part.startswith(".") for part in path.relative_to(root).parts[:-1]):
            continue
        if path.is_file() and not parser.should_skip(str(path.relative_to(root))):
            yield path


def build_graph(root: Path) -> tuple[nx.MultiDiGraph, dict[str, Any]]:
    """Parse the repository and return (graph, build_stats)."""
    graph = nx.MultiDiGraph()
    all_facts: list[parser.FileFacts] = []
    skipped = 0
    for abs_path in _iter_source_files(root):
        rel = str(abs_path.relative_to(root))
        facts = parser.parse_file(rel, abs_path)
        if facts is None:
            skipped += 1
            continue
        all_facts.append(facts)

    module_index = _module_index(root)
    func_index: dict[str, list[str]] = {}
    class_index: dict[str, list[str]] = {}

    # --- nodes ------------------------------------------------------------ #
    for facts in all_facts:
        graph.add_node(facts.file, id=facts.file, label=Path(facts.file).name, kind="module",
                       file=facts.file, line=1, end_line=0, loc=0, qualname=_module_name(facts.file),
                       test=facts.is_test_file, doc="", language=facts.language)
        for sym in facts.symbols:
            node_id = f"{facts.file}::{sym.qualname}"
            is_test_sym = facts.is_test_file and sym.kind == "function" and (
                sym.name.startswith("test_") or sym.parent.startswith("Test"))
            kind = "test_function" if is_test_sym else sym.kind
            graph.add_node(
                node_id, id=node_id, label=sym.name, kind=kind, file=facts.file,
                line=sym.start_line, end_line=sym.end_line,
                loc=max(1, sym.end_line - sym.start_line + 1), qualname=sym.qualname,
                test=is_test_sym or (facts.is_test_file and sym.kind == "class"
                                     and sym.name.startswith("Test")),
                doc=(sym.doc or "").split("\n")[0][:200], language=facts.language)
            (func_index if sym.kind == "function" else class_index).setdefault(sym.name, []).append(node_id)
            graph.add_edge(facts.file, node_id, type="defines", id="")

    # --- imports ---------------------------------------------------------- #
    unresolved_imports = 0
    for facts in all_facts:
        for imp in facts.imports:
            targets: list[str] = []
            if imp.kind == "import":
                if imp.module in module_index:
                    targets.append(imp.module)
                elif imp.module.split(".")[0] in module_index:
                    targets.append(imp.module.split(".")[0])
            else:
                base = imp.module
                if imp.level:
                    pkg_parts = _module_name(facts.file).split(".")
                    if Path(facts.file).name != "__init__.py":
                        pkg_parts = pkg_parts[:-1]
                    keep = len(pkg_parts) - (imp.level - 1)
                    pkg = ".".join(pkg_parts[: max(0, keep)])
                    base = f"{pkg}.{imp.module}" if imp.module else pkg
                    base = base.strip(".")
                candidates = [base] if base else []
                for name in imp.names:
                    if name == "*":
                        continue
                    full = f"{base}.{name}" if base else name
                    candidates.append(full)
                for cand in candidates:
                    if cand in module_index:
                        targets.append(module_index[cand])
                        break
            if not targets and imp.kind == "from":
                # `from . import util` style already handled; count misses for stats.
                unresolved_imports += 1
            for target_mod in targets:
                target_file = module_index.get(target_mod, target_mod)
                if target_file == facts.file:
                    continue
                if not _has_edge_type(graph, facts.file, target_file, "imports"):
                    graph.add_edge(facts.file, target_file, type="imports",
                                   line=imp.line, id="")

    # --- calls ------------------------------------------------------------ #
    resolved_calls = unresolved_calls = 0
    for facts in all_facts:
        for call in facts.calls:
            if call.callee_name in BUILTIN_SKIP or len(call.callee_name) < 2:
                unresolved_calls += 1
                continue
            caller = (f"{facts.file}::{call.caller_qualname}" if call.caller_qualname
                      else facts.file)
            if caller not in graph:
                continue
            candidates = func_index.get(call.callee_name, [])
            if not candidates:
                unresolved_calls += 1
                continue
            same_file = [c for c in candidates if c.split("::")[0] == facts.file]
            chosen = same_file or candidates
            if call.qualifier in {"self", "cls"} and same_file:
                chosen = same_file
            for target in chosen:
                if graph.nodes[caller].get("test") and not graph.nodes[target].get("test"):
                    edge_type = "tests"
                else:
                    edge_type = "calls"
                if _has_edge_type(graph, caller, target, edge_type):
                    continue
                graph.add_edge(caller, target, type=edge_type, line=call.line,
                               qualifier=call.qualifier, id="")
                resolved_calls += 1

    # --- inheritance ------------------------------------------------------ #
    for facts in all_facts:
        for class_qual, base in facts.inherits:
            if base in BUILTIN_SKIP:
                continue
            source = f"{facts.file}::{class_qual}"
            if source not in graph:
                continue
            same = [c for c in class_index.get(base, []) if c.split("::")[0] == facts.file]
            targets = same or class_index.get(base, [])
            for target in targets:
                if not _has_edge_type(graph, source, target, "inherits"):
                    graph.add_edge(source, target, type="inherits", id="")

    # --- test heuristics (name -> implementation) ------------------------- #
    for facts in all_facts:
        for sym in facts.symbols:
            if not (sym.kind == "function" and sym.name.startswith("test_") and facts.is_test_file):
                continue
            test_id = f"{facts.file}::{sym.qualname}"
            remainder = sym.name[len("test_"):]
            hits = func_index.get(remainder, [])
            if not hits:
                # prefix match at word boundaries: test_create_order_x -> create_order
                for fname, ids in func_index.items():
                    if remainder.startswith(fname) and (
                            len(remainder) == len(fname) or remainder[len(fname)] == "_"):
                        hits.extend(ids)
            for hit in hits[:3]:
                if hit.split("::")[0] == facts.file:
                    continue
                if not _has_edge_type(graph, test_id, hit, "tests"):
                    graph.add_edge(test_id, hit, type="tests", heuristic=True, id="")

    # Assign stable edge ids.
    for i, (src, dst, key, data) in enumerate(graph.edges(keys=True, data=True)):
        data["id"] = f"e{i}"
        data["source"] = src
        data["target"] = dst

    stats = {
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "files_parsed": len(all_facts),
        "files_skipped": skipped,
        "resolved_calls": resolved_calls,
        "unresolved_calls": unresolved_calls,
        "unresolved_imports": unresolved_imports,
        "by_kind": _count_by(graph, "kind"),
        "by_edge": _count_edges_by_type(graph),
    }
    return graph, stats


def _count_by(graph: nx.MultiDiGraph, attr: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for _, data in graph.nodes(data=True):
        key = str(data.get(attr, "?"))
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def _count_edges_by_type(graph: nx.MultiDiGraph) -> dict[str, int]:
    out: dict[str, int] = {}
    for _, _, data in graph.edges(data=True):
        key = str(data.get("type", "?"))
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))
