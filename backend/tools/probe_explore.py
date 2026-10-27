"""Exploration probe: verify each system's mock explore stage on a repo.

Drives the real MockLLM + real tools (file/graph/GNN) through the explore
stage in-process, then runs one edit-stage call with a faithful stage message
to see whether the evidence gate lets the scripted fixture through.

Usage:
    .venv/bin/python backend/tools/probe_explore.py [source_dir] [task_text]
Defaults: examples/flowgate + FLOWGATE_TASK_TEXT.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.stages import fence                      # noqa: E402
from app.agents.systems import build_tools               # noqa: E402
from app.benchmark.tasks import FLOWGATE_TASK_TEXT       # noqa: E402
from app.graph import builder                            # noqa: E402
from app.llm.mock import MockLLM, _task_keyword          # noqa: E402


def simulate(system: str, ws: Path, graph, task: str):
    ctx = SimpleNamespace(system=system, graph=graph, workspace=ws, task=task,
                          on_graph_visit=lambda ids, why: None,
                          on_edit=lambda *a: None)
    tools = build_tools(ctx, "explore")
    toolmap = {t.name: t for t in tools}
    schemas = [t.schema for t in tools]
    llm = MockLLM()
    meta = {"stage": "explore", "task": task, "workspace": str(ws)}
    messages: list[dict] = [{"role": "user", "content": f"## TASK\n{task}"}]
    reads: list[str] = []
    report: dict = {}
    calls: list[str] = []

    for _ in range(12):
        res = llm.chat(messages, schemas, meta=meta)
        if not res.tool_calls:
            report = json.loads(res.content) if res.content else {}
            break
        messages.append({"role": "assistant", "content": res.content or None,
                         "tool_calls": [{"id": tc.id, "type": "function",
                                         "function": {"name": tc.name,
                                                      "arguments": json.dumps(tc.args)}}
                                        for tc in res.tool_calls]})
        for tc in res.tool_calls:
            calls.append(tc.name)
            out = toolmap[tc.name].handler(tc.args or {})
            if tc.name == "read_file":
                reads.append(str(tc.args.get("path")))
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(out, ensure_ascii=False, default=str)})

    # One edit-stage call with the real stage message shape (TASK + EXPLORE
    # REPORT + PLAN fences) to exercise the evidence gate.
    plan = json.dumps({"steps": [{"step": "explore", "files": sorted(set(reads))}]})
    edit_user = (f"## TASK\n{task}\n\n## EXPLORE REPORT\n{fence(report)}\n\n"
                 f"## IMPLEMENTATION PLAN\n{fence(plan)}\n\nImplement the plan now.")
    edit_tools = build_tools(ctx, "edit")
    edit_res = llm.chat([{"role": "user", "content": edit_user}],
                        [t.schema for t in edit_tools],
                        meta={"stage": "edit", "task": task, "workspace": str(ws)})
    edit_action = (edit_res.tool_calls[0].name if edit_res.tool_calls else "no tool call")
    edit_path = (edit_res.tool_calls[0].args.get("path")
                 if edit_res.tool_calls else "-")

    return {"calls": calls, "reads": reads, "report": report,
            "edit_action": edit_action, "edit_path": edit_path}


def main() -> int:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "examples/flowgate"
    task = sys.argv[2] if len(sys.argv) > 2 else FLOWGATE_TASK_TEXT
    if len(sys.argv) > 3:
        target = sys.argv[3]
    else:
        target = "orders/service.py" if "sample" in source.name else "app/dispatcher.py"

    graph, stats = builder.build_graph(source)
    print(f"repo      : {source}")
    print(f"keyword   : {_task_keyword(task)!r}")
    print(f"graph     : {stats.get('nodes')} nodes, {stats.get('edges')} edges")
    print(f"target    : {target}")
    print()

    ok = True
    for system in "ABC":
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "ws"
            shutil.copytree(source, ws)
            result = simulate(system, ws, graph, task)
        inspected = result["report"].get("files_inspected") or []
        hit = target in inspected
        gate = ("APPLY fixture" if result["edit_path"] == target
                else f"no fixture ({result['edit_action']})")
        expected = (system != "A") if "flowgate" in str(source) else True
        status = "OK " if hit == expected else "!! "
        if hit != expected:
            ok = False
        print(f"System {system} {status}calls={result['calls']}")
        print(f"         reads   = {inspected}")
        print(f"         gate    = {gate}")
        print()
    print("PASS: exploration matches the expected story for this repo"
          if ok else "FAIL: expectations not met")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
