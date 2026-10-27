"""Workspace file and terminal tools shared by all three systems.

Fair-comparison invariant: every system gets the identical file/terminal
toolset; only graph (B) and GNN (C) tools differ.
"""
from __future__ import annotations

import fnmatch
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .. import config
from .testparse import parse_pytest

IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".pytest_cache",
                ".mypy_cache", "dist", "build", ".next", ".cache"}
MAX_LIST_ENTRIES = 200
DEFAULT_READ_LINES = 150
MAX_READ_LINES = 400
MAX_GREP_MATCHES = 60


@dataclass
class Tool:
    name: str
    description: str
    properties: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]
    required: list[str] = None  # type: ignore[assignment]

    @property
    def schema(self) -> dict[str, Any]:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description,
                             "parameters": {"type": "object", "properties": self.properties,
                                            "required": self.required or []}}}


class UnsafePath(ValueError):
    pass


def resolve_in_workspace(workspace: Path, rel_path: str) -> Path:
    if not rel_path or rel_path.strip() in {"", ".", "./"}:
        return workspace
    target = (workspace / rel_path).resolve()
    root = workspace.resolve()
    if target != root and root not in target.parents:
        raise UnsafePath(f"path escapes the workspace: {rel_path}")
    return target


def _walk(workspace: Path):
    stack = [workspace]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.name in IGNORED_DIRS or entry.name.startswith("."):
                continue
            if entry.is_dir():
                stack.append(entry)
            else:
                yield entry


def build_file_tools(ctx) -> list[Tool]:
    workspace: Path = ctx.workspace

    def list_dir(args: dict) -> dict:
        target = resolve_in_workspace(workspace, str(args.get("path") or ""))
        if not target.is_dir():
            raise FileNotFoundError(f"not a directory: {args.get('path')}")
        entries = []
        for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if child.name.startswith(".") or child.name in IGNORED_DIRS:
                continue
            rel = str(child.relative_to(workspace))
            entries.append({"name": child.name, "path": rel,
                            "type": "dir" if child.is_dir() else "file",
                            **({"bytes": child.stat().st_size} if child.is_file() else {})})
            if len(entries) >= MAX_LIST_ENTRIES:
                break
        rel_dir = str(target.relative_to(workspace)) if target != workspace else ""
        return {"path": rel_dir, "entries": entries, "truncated": len(entries) >= MAX_LIST_ENTRIES}

    def read_file(args: dict) -> dict:
        target = resolve_in_workspace(workspace, str(args.get("path") or ""))
        if not target.is_file():
            raise FileNotFoundError(f"not a file: {args.get('path')}")
        if target.stat().st_size > 1_000_000:
            raise ValueError("file too large to read (>1MB)")
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        try:
            offset = max(1, int(args.get("offset") or 1))
        except (TypeError, ValueError):
            offset = 1
        try:
            limit = min(MAX_READ_LINES, max(1, int(args.get("limit") or DEFAULT_READ_LINES)))
        except (TypeError, ValueError):
            limit = DEFAULT_READ_LINES
        window = lines[offset - 1:offset - 1 + limit]
        return {"path": str(args.get("path")), "content": "\n".join(window),
                "start_line": offset, "lines_returned": len(window),
                "total_lines": len(lines),
                "truncated": offset - 1 + len(window) < len(lines)}

    def grep(args: dict) -> dict:
        pattern = str(args.get("pattern") or "").strip()
        if not pattern:
            raise ValueError("pattern is required")
        glob = str(args.get("glob") or "*")
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(pattern), re.IGNORECASE)
        matches: list[dict[str, Any]] = []
        truncated = False
        for path in _walk(workspace):
            rel = str(path.relative_to(workspace))
            if not fnmatch.fnmatch(rel, glob) and not fnmatch.fnmatch(path.name, glob):
                continue
            try:
                if path.stat().st_size > 600_000:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    matches.append({"path": rel, "line": i, "text": line.strip()[:240]})
                    if len(matches) >= MAX_GREP_MATCHES:
                        truncated = True
                        break
            if truncated:
                break
        return {"pattern": pattern, "glob": glob, "matches": matches,
                "count": len(matches), "truncated": truncated}

    def write_file(args: dict) -> dict:
        rel_path = str(args.get("path") or "").strip()
        content = args.get("content")
        if not rel_path or not isinstance(content, str):
            raise ValueError("path and string content are required")
        target = resolve_in_workspace(workspace, rel_path)
        if target.is_dir():
            raise ValueError(f"is a directory: {rel_path}")
        old = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
        action = "modify" if target.exists() else "create"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        ctx.on_edit(rel_path, action, old, content)
        return {"path": rel_path, "action": action, "bytes": len(content.encode("utf-8")),
                "lines": content.count("\n") + 1}

    def run_tests(args: dict) -> dict:
        cmd = str(args.get("cmd") or "").strip()
        env = ctx.exec_env
        if cmd:
            result = env.run_shell(cmd, timeout=config.TEST_TIMEOUT_SEC)
            parsed = parse_pytest(result.combined, result.exit_code)
            parsed.update({"command": cmd, "ok": result.ok and parsed["failed"] == 0,
                           "exit_code": result.exit_code, "mode": result.mode,
                           "output": result.combined[-6000:]})
            return parsed
        has_pytest_files = any(
            p.name.startswith("test_") or p.name.endswith("_test.py")
            or any(part in {"tests", "test", "spec"} for part in p.parts)
            for p in workspace.rglob("*.py") if not any(x in p.parts for x in IGNORED_DIRS))
        pkg = workspace / "package.json"
        if not has_pytest_files and pkg.is_file():
            try:
                scripts = json.loads(pkg.read_text()).get("scripts") or {}
            except ValueError:
                scripts = {}
            if scripts.get("test"):
                result = env.run_shell("npm test --silent", timeout=config.TEST_TIMEOUT_SEC)
                return {"command": "npm test", "ok": result.ok, "passed": 0, "failed": 0 if result.ok else 1,
                        "failures": [], "summary": ("npm test passed" if result.ok else "npm test failed"),
                        "output": result.combined[-6000:], "exit_code": result.exit_code,
                        "mode": result.mode}
        pytest_argv = ["python", "-m", "pytest", "-q", "--tb=short", "-rf", "."]
        result = env.run_argv(pytest_argv, timeout=config.TEST_TIMEOUT_SEC)
        parsed = parse_pytest(result.combined, result.exit_code)
        parsed.update({"command": "pytest -q --tb=short -rf",
                       "ok": result.ok and parsed["failed"] == 0 and not parsed["no_tests"],
                       "exit_code": result.exit_code, "mode": result.mode,
                       "output": result.combined[-6000:]})
        return parsed

    def run_command(args: dict) -> dict:
        command = str(args.get("command") or "").strip()
        if not command:
            raise ValueError("command is required")
        started = time.monotonic()
        result = ctx.exec_env.run_shell(command, timeout=min(120, config.TEST_TIMEOUT_SEC))
        return {"command": command, "ok": result.ok, "exit_code": result.exit_code,
                "output": result.combined[-8000:], "duration_ms": result.duration_ms or
                int((time.monotonic() - started) * 1000), "mode": result.mode}

    return [
        Tool("list_dir", "List files and directories at a path relative to the repo root.",
             {"path": {"type": "string", "description": "Relative directory path ('' for root)"}},
             list_dir),
        Tool("read_file", "Read a source file (windowed by line offset/limit).",
             {"path": {"type": "string", "description": "Relative file path"},
              "offset": {"type": "integer", "description": "1-based start line (default 1)"},
              "limit": {"type": "integer", "description": f"max lines (default {DEFAULT_READ_LINES})"}},
             read_file, required=["path"]),
        Tool("grep", "Search file contents with a regular expression (case-insensitive).",
             {"pattern": {"type": "string", "description": "Regex or literal search text"},
              "glob": {"type": "string", "description": "Filename/path glob filter, e.g. '*.py'"}},
             grep, required=["pattern"]),
        Tool("write_file", "Create or overwrite a file with complete new content. "
                           "Records a diff of the change.",
             {"path": {"type": "string", "description": "Relative file path"},
              "content": {"type": "string", "description": "Complete new file content"}},
             write_file, required=["path", "content"]),
        Tool("run_tests", "Run the repository's test suite (pytest or npm test), or a custom "
                          "shell command. Returns parsed pass/fail counts and failures.",
             {"cmd": {"type": "string", "description": "Optional custom test command"}},
             run_tests),
        Tool("run_command", "Run a shell command inside the isolated workspace (sandboxed, "
                            "time-limited).",
             {"command": {"type": "string", "description": "Shell command to execute"}},
             run_command, required=["command"]),
    ]
