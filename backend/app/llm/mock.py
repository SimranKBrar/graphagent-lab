"""Deterministic scripted LLM used when no OPENAI_API_KEY is configured.

The mock is content-aware: it drives the real tool loop (list/grep/read,
graph queries, write, run_tests) with scripted strategies per stage and per
system, then returns structured JSON shaped like the production prompts'
contracts. This makes the full platform runnable — including honest visible
vs. hidden test evaluation — without network access or a key.

Strategies:
  explore A: list_dir -> grep -> read top matches
  explore B: graph_search -> graph_neighbors -> read top nodes' files
  explore C: gnn_relevance -> graph_impact -> read impacted files
  plan:      structured steps derived from the embedded explore report
  edit:      fixture edit when the task matches one AND exploration read the
             target file (evidence gate), else read + no changes
  test:      run_tests once, report the parsed result
  repair:    fixture corrective edit when the fixture defines one, else a
             diagnosis derived from the failures (target: edit)
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional

from .client import BaseLLM, LLMResult, ToolCall, estimate_tokens
from .fixtures import load_fixture_content, match_fixture
from .jsonutil import extract_json, json_blocks

STOPWORDS = {"the", "and", "for", "with", "that", "this", "fix", "add", "bug", "when",
             "all", "not", "are", "but", "you", "can", "has", "have", "from", "into",
             "should", "must", "please", "make", "sure", "does", "code", "repo", "test",
             "tests", "issue", "problem", "feature", "change", "ensure", "system"}
SOURCE_SUFFIXES = (".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rb")


def _task_keyword(task: str) -> str:
    """Most specific task token for search-based exploration.

    Longest non-stopword wins: 'create_order' beats 'orders', which would
    otherwise match every file in the package. Falls back to the first
    qualifying word, then a generic probe.
    """
    words = [w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", task or "")
             if len(w) > 3 and w.lower() not in STOPWORDS]
    if not words:
        return "def"
    return max(words, key=len)


def _short(task: str, limit: int = 160) -> str:
    text = " ".join((task or "").split())
    return text[:limit] + ("…" if len(text) > limit else "")


class _Step:
    def __init__(self, name: str, args: dict[str, Any], result: Any):
        self.name = name
        self.args = args
        self.result = result if isinstance(result, dict) else {}


class MockLLM(BaseLLM):
    mode = "mock"

    def __init__(self, model: Optional[str] = None):
        self.model = model or "mock-scripted"

    # ------------------------------------------------------------------ #
    def chat(self, messages, tools=None, meta=None) -> LLMResult:
        meta = dict(meta or {})
        stage = meta.get("stage") or "explore"
        tool_names = set()
        for tool in tools or []:
            fn = tool.get("function") or tool
            if fn.get("name"):
                tool_names.add(fn["name"])
        steps = self._replay(messages)
        handler = getattr(self, f"_stage_{stage}", None)
        if handler is None:
            handler = self._stage_explore
        content, tool_calls = handler(meta, tool_names, steps, messages)
        content = content or ""
        tool_calls = tool_calls or []
        prompt_chars = sum(len(str(m.get("content") or "")) +
                           len(str(m.get("tool_calls") or "")) for m in messages)
        completion_chars = len(content) + sum(len(json.dumps(a)) for _, a in tool_calls)
        return LLMResult(
            content=content,
            tool_calls=[ToolCall(id=f"mock_{i}_{int(time.time()*1000) % 100000}",
                                 name=name, args=args)
                        for i, (name, args) in enumerate(tool_calls)],
            model=self.model, mock=True,
            prompt_tokens=max(1, prompt_chars // 4) + 30,
            completion_tokens=max(1, completion_chars // 4) + 10,
            duration_ms=25)

    @staticmethod
    def _replay(messages) -> list[_Step]:
        """Pair assistant tool_calls with their tool results, in order."""
        pending: dict[str, tuple[str, dict[str, Any]]] = {}
        steps: list[_Step] = []
        for msg in messages:
            role = msg.get("role")
            if role == "assistant" and msg.get("tool_calls"):
                for call in msg["tool_calls"]:
                    fn = call.get("function") or {}
                    args_raw = fn.get("arguments") or "{}"
                    try:
                        args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
                    except ValueError:
                        args = {}
                    pending[call.get("id") or ""] = (fn.get("name") or "", args)
            elif role == "tool":
                name, args = pending.pop(msg.get("tool_call_id") or "", ("", {}))
                try:
                    result = json.loads(msg.get("content") or "{}")
                except ValueError:
                    result = {"raw": str(msg.get("content") or "")[:2000]}
                if name:
                    steps.append(_Step(name, args, result))
        return steps

    @staticmethod
    def _user_text(messages) -> str:
        for msg in reversed(messages):
            if msg.get("role") == "user":
                return str(msg.get("content") or "")
        return ""

    @staticmethod
    def _block(messages, *keys: str) -> dict[str, Any]:
        for block in json_blocks(MockLLM._user_text(messages)):
            if any(k in block for k in keys):
                return block
        return {}

    # ------------------------------------------------------------------ #
    # explore
    # ------------------------------------------------------------------ #
    def _stage_explore(self, meta, tool_names, steps, messages):
        task = str(meta.get("task") or "")
        keyword = _task_keyword(task)
        read_paths = {s.args.get("path") for s in steps if s.name == "read_file"}
        done = [s.name for s in steps]
        candidates = self._candidates(steps, keyword)

        if "gnn_relevance" in tool_names:
            if "gnn_relevance" not in done:
                return None, [("gnn_relevance", {"task": task, "top_k": 8})]
            if "graph_impact" not in done:
                node = self._first_node(steps, "gnn_relevance")
                if node:
                    return None, [("graph_impact", {"node_id": node, "depth": 2})]
        elif "graph_search" in tool_names:
            if "graph_search" not in done:
                return None, [("graph_search", {"query": keyword, "limit": 12})]
            if "graph_neighbors" not in done:
                node = self._first_node(steps, "graph_search")
                if node:
                    return None, [("graph_neighbors",
                                   {"node_id": node, "direction": "both", "limit": 15})]
        else:
            if "list_dir" not in done:
                return None, [("list_dir", {"path": ""})]
            if "grep" not in done:
                return None, [("grep", {"pattern": keyword, "glob": "*"})]

        unread = [p for p in candidates if p and p not in read_paths]
        if unread and len(read_paths) < 2 and len(steps) < 6:
            return None, [("read_file", {"path": unread[0]})]
        if len(read_paths) < 2 and len(steps) < 5:
            # second pass over remaining candidates (A-path after first read)
            more = [p for p in candidates if p not in read_paths]
            if more:
                return None, [("read_file", {"path": more[0]})]
        return self._explore_report(steps, keyword, read_paths), []

    @staticmethod
    def _candidates(steps: list[_Step], keyword: str) -> list[str]:
        entries: list[tuple[int, int, str]] = []

        def add(path: Optional[str], priority: int = 1, kw_path: bool = False):
            if not path or not isinstance(path, str):
                return
            if not path.endswith(SOURCE_SUFFIXES):
                priority += 2
            # "keyword appears in the path" is a text-search relevance hint,
            # so it only applies to grep candidates; graph results were already
            # ranked by label/qualname/path relevance and are kept in score
            # order (insertion) rather than re-sorted alphabetically.
            if kw_path and keyword and keyword.lower() in path.lower():
                priority -= 1
            if "/tests/" in path or path.startswith("tests/") or "test_" in path.split("/")[-1]:
                priority += 1
            entries.append((priority, len(entries), path))

        for step in steps:
            if step.name == "grep":
                for match in (step.result.get("matches") or [])[:12]:
                    add(match.get("path"), 1, kw_path=True)
            elif step.name in {"graph_search", "gnn_relevance"}:
                results = (step.result.get("results") or step.result.get("predictions") or [])
                for item in results[:8]:
                    node = item.get("node") or item
                    add(node.get("file"), 0)
            elif step.name in {"graph_impact", "graph_neighbors"}:
                for key in ("node", "affected", "neighbors", "dependencies"):
                    items = step.result.get(key)
                    if isinstance(items, dict):
                        items = [items]
                    for item in (items or [])[:8]:
                        add(item.get("file"), 0 if key in {"node", "affected"} else 2)
        entries.sort(key=lambda triple: (triple[0], triple[1]))
        seen: set[str] = set()
        ordered: list[str] = []
        for _, _, path in entries:
            if path not in seen:
                seen.add(path)
                ordered.append(path)
        return ordered

    @staticmethod
    def _first_node(steps: list[_Step], tool: str) -> Optional[str]:
        for step in steps:
            if step.name != tool:
                continue
            for key in ("results", "predictions", "affected"):
                for item in (step.result.get(key) or [])[:6]:
                    node = item.get("node") or item
                    if node.get("id"):
                        return str(node["id"])
        return None

    def _explore_report(self, steps, keyword, read_paths) -> str:
        findings: list[dict[str, str]] = []
        symbols: list[str] = []
        seen_files: set[str] = set()

        for step in steps:
            if step.name == "grep":
                for match in (step.result.get("matches") or [])[:20]:
                    path = match.get("path")
                    text = str(match.get("text") or "").strip()
                    if not path or path in seen_files:
                        continue
                    seen_files.add(path)
                    findings.append({"file": path, "note": f"L{match.get('line')}: {text[:140]}"})
                    m = re.search(r"\b(?:def|class|function)\s+([A-Za-z_]\w*)", text)
                    if m:
                        symbols.append(f"{path}::{m.group(1)}")
            elif step.name in {"graph_search", "gnn_relevance"}:
                results = (step.result.get("results") or step.result.get("predictions") or [])
                for item in results[:8]:
                    node = item.get("node") or item
                    path = node.get("file")
                    label = node.get("label") or node.get("id")
                    if node.get("id"):
                        symbols.append(str(node["id"]))
                    if path and path not in seen_files:
                        seen_files.add(path)
                        note = f"{label} ({node.get('kind')}, line {node.get('line')})"
                        if item.get("score") is not None:
                            note += f" — relevance {item['score']}"
                        findings.append({"file": path, "note": note})
            elif step.name in {"graph_impact", "graph_neighbors"}:
                node = step.result.get("node") or {}
                for item in (step.result.get("affected") or [])[:6]:
                    path = item.get("file")
                    if path and path not in seen_files:
                        seen_files.add(path)
                        findings.append({"file": path,
                                         "note": f"depends on {node.get('label', 'target')} "
                                                 f"({item.get('label')})"})

        for path in sorted(read_paths):
            if path and path not in seen_files:
                seen_files.add(path)
                findings.append({"file": path, "note": "inspected source directly"})

        notes = (f"Located {len(findings)} candidate file(s) via keyword '{keyword}' "
                 f"using available tools; {len(read_paths)} file(s) read in full.")
        report = {"findings": findings[:8], "symbols": symbols[:20],
                  "files_inspected": sorted(p for p in read_paths if p), "notes": notes}
        return json.dumps(report, indent=2)

    # ------------------------------------------------------------------ #
    # plan
    # ------------------------------------------------------------------ #
    def _stage_plan(self, meta, tool_names, steps, messages):
        task = str(meta.get("task") or "")
        explore = self._block(messages, "findings", "files_inspected")
        findings = explore.get("findings") or []
        files: list[str] = []
        for finding in findings:
            path = finding.get("file")
            if path and path not in files:
                files.append(path)
        files = files[:5]
        plan_steps = []
        for i, path in enumerate(files, start=1):
            plan_steps.append({
                "id": f"S{i}",
                "description": (f"Inspect {path} and apply the required change for: "
                                f"{_short(task, 100)}"),
                "files": [path],
                "symbols": [s for s in (explore.get("symbols") or [])
                            if str(s).startswith(path)][:4],
            })
        plan_steps.append({
            "id": f"S{len(plan_steps) + 1}",
            "description": "Run the validation suite and confirm no regressions remain.",
            "files": [], "symbols": [],
        })
        plan = {"steps": plan_steps,
                "risks": ["Changes may affect callers of modified functions — "
                          "verify dependent components and tests."]}
        return json.dumps(plan, indent=2), []

    # ------------------------------------------------------------------ #
    # edit
    # ------------------------------------------------------------------ #
    def _stage_edit(self, meta, tool_names, steps, messages):
        task = str(meta.get("task") or "")
        workspace = Path(str(meta.get("workspace") or "."))
        fixture = match_fixture(task, workspace)
        writes = [s for s in steps if s.name == "write_file"]

        if fixture and not writes:
            # Evidence gate: the scripted fix is only applied when this system's
            # exploration actually inspected the target file. Exploration quality
            # therefore decides whether the mock can act on its knowledge — a
            # system that grep/gnn-navigated to the wrong files reports no
            # confident change instead of silently succeeding. (For the sample
            # task every system reads orders/service.py, so that story is
            # unchanged.)
            explore = self._block(messages, "findings", "files_inspected")
            inspected = {str(p) for p in (explore.get("files_inspected") or [])}
            if all(str(e.get("path")) in inspected for e in fixture.edits):
                edit = fixture.edits[0]
                return None, [("write_file", {"path": edit["path"],
                                              "content": load_fixture_content(edit)})]
        if writes:
            last = writes[-1]
            edits = [{"path": last.args.get("path"),
                      "action": (last.result.get("action") or "modify"),
                      "rationale": f"Implements the planned fix for: {_short(task, 100)}"}]
            return json.dumps({"edits": edits,
                               "notes": "Applied the planned change; ready for validation."},
                              indent=2), []

        # No scripted solution: read the first planned file for diligence,
        # then report that no confident change was identified.
        plan = self._block(messages, "steps")
        steps_list = plan.get("steps") or []
        read_paths = {s.args.get("path") for s in steps if s.name == "read_file"}
        for plan_step in steps_list:
            for path in plan_step.get("files") or []:
                if path and path not in read_paths and not steps:
                    return None, [("read_file", {"path": path})]
        return json.dumps({
            "edits": [],
            "notes": ("Mock mode has no scripted solution for this task; "
                      "no changes were applied."),
        }, indent=2), []

    # ------------------------------------------------------------------ #
    # test
    # ------------------------------------------------------------------ #
    def _stage_test(self, meta, tool_names, steps, messages):
        runs = [s for s in steps if s.name == "run_tests"]
        if not runs and "run_tests" in tool_names:
            return None, [("run_tests", {})]
        result = runs[-1].result if runs else {}
        passed = int(result.get("passed") or 0)
        failed = int(result.get("failed") or 0)
        report = {
            "passed": passed,
            "failed": failed,
            "failures": result.get("failures") or [],
            "commands": [result.get("command") or "pytest -q"] if result.get("command") else [],
            "summary": (result.get("summary")
                        or (f"{passed} passed, {failed} failed"
                            if (passed or failed) else "no tests were executed")),
        }
        return json.dumps(report, indent=2), []

    # ------------------------------------------------------------------ #
    # repair
    # ------------------------------------------------------------------ #
    def _stage_repair(self, meta, tool_names, steps, messages):
        task = str(meta.get("task") or "")
        workspace = Path(str(meta.get("workspace") or "."))
        report = self._block(messages, "passed", "failed", "failures")
        failures = report.get("failures") or []
        fixture = match_fixture(task, workspace)
        writes = [s for s in steps if s.name == "write_file"]

        if fixture and fixture.repair and failures and not writes:
            edit = fixture.repair["edits"][0]
            return None, [("write_file", {"path": edit["path"],
                                          "content": load_fixture_content(edit)})]
        if fixture and fixture.repair and writes:
            repair = fixture.repair
            payload = {
                "diagnosis": repair.get("diagnosis", ""),
                "root_cause": repair.get("root_cause", ""),
                "target_stage": repair.get("target_stage", "test"),
                "notes": "Corrective patch applied; re-run validation.",
            }
            return json.dumps(payload, indent=2), []

        names = ", ".join(str(f.get("name") or f.get("error") or "?")
                          for f in failures[:5]) or "unknown tests"
        payload = {
            "diagnosis": (f"Failing tests: {names}. The current change does not satisfy "
                          f"the expected behavior for: {_short(task, 120)}."),
            "root_cause": ("Uncertain (mock mode) — likely an incomplete or incorrect "
                           "modification of the targeted component."),
            "target_stage": "edit" if failures else "test",
            "notes": "No scripted corrective patch available for this task.",
        }
        return json.dumps(payload, indent=2), []
