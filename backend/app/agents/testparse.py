"""Parse pytest output into structured results (shared by tools and mock)."""
from __future__ import annotations

import re
from typing import Any

SUMMARY_RE = re.compile(r"(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed|deselected)")
FAILED_LINE_RE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+?::\S+?)\s+(?:-\s+(.*))?$", re.MULTILINE)
SECTION_RE = re.compile(r"^_+\s+(test[\w:.\[\] ]*?)\s+_+\s*$", re.MULTILINE)
FILE_LINE_RE = re.compile(r"([\w./\\-]+\.py):(\d+)")


def parse_pytest(output: str, exit_code: int | None = None) -> dict[str, Any]:
    text = output or ""
    counts: dict[str, int] = {}
    for amount, kind in SUMMARY_RE.findall(text):
        key = "errors" if kind.startswith("error") else kind
        counts[key] = max(counts.get(key, 0), int(amount))
    passed = counts.get("passed", 0)
    failed = counts.get("failed", 0) + counts.get("errors", 0)

    failures: list[dict[str, Any]] = []
    # Preferred: pytest -rf FAILED summary lines.
    for node_id, reason in FAILED_LINE_RE.findall(text):
        if "::" in node_id:
            file_part, _, test_name = node_id.partition("::")
        else:
            file_part, test_name = "", node_id
        failures.append({"name": test_name.split("[")[0], "file": file_part or None,
                         "line": None, "error": (reason or "").strip()[:400]})
    # Fill line numbers from traceback sections when available.
    if failures:
        # Pattern emitted by --tb=short even outside section headers:
        #   tests/test_service.py:42: in test_reserves
        for file_part, line_no, name in re.findall(
                r"([\w./\\-]+\.py):(\d+):\s+in\s+(\S+)", text):
            for failure in failures:
                if failure["name"] == name and failure.get("line") is None:
                    failure["file"] = failure.get("file") or file_part
                    failure["line"] = int(line_no)
        sections = list(SECTION_RE.finditer(text))
        for i, section in enumerate(sections):
            start = section.end()
            end = sections[i + 1].start() if i + 1 < len(sections) else len(text)
            body = text[start:end]
            file_line = FILE_LINE_RE.search(body)
            if not file_line:
                continue
            name = section.group(1).strip().split(" ")[0]
            for failure in failures:
                if failure["name"] == name and failure.get("line") is None:
                    failure["file"] = failure.get("file") or file_line.group(1)
                    failure["line"] = int(file_line.group(2))
                    if not failure.get("error"):
                        first_e = re.search(r"^E\s+(.*)$", body, re.MULTILINE)
                        failure["error"] = (first_e.group(1) if first_e else "")[:400]

    no_tests = bool(re.search(r"no tests ran|collected 0 items", text, re.IGNORECASE))
    summary = ""
    for line in reversed(text.strip().splitlines()):
        if re.search(r"\d+\s+(passed|failed|no tests ran|error)", line):
            summary = line.strip("= ").strip()[:200]
            break
    if not summary and no_tests:
        summary = "no tests were executed"
    ok = (exit_code == 0) if exit_code is not None else (failed == 0 and not no_tests)
    return {"passed": passed, "failed": failed, "failures": failures[:10],
            "summary": summary or ("ok" if ok else "failed"),
            "no_tests": no_tests, "ok": ok}
