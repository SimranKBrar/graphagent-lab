"""Tolerant JSON extraction from LLM responses."""
from __future__ import annotations

import json
import re
from typing import Any, Optional

FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _balanced(text: str) -> Optional[str]:
    """Return the first top-level balanced {...} object in text."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def extract_json(text: str) -> Optional[dict[str, Any]]:
    """Best-effort parse of the first JSON object in an LLM message."""
    if not text:
        return None
    candidate: Optional[str] = None
    for match in FENCE_RE.finditer(text):
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            continue
    candidate = _balanced(text)
    if candidate is None:
        return None
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        # Repair common issues: trailing commas, single quotes are left alone.
        repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            parsed = json.loads(repaired)
            return parsed if isinstance(parsed, dict) else None
        except ValueError:
            return None


def json_blocks(text: str) -> list[dict[str, Any]]:
    """All fenced JSON objects in a message (used to read embedded reports)."""
    out: list[dict[str, Any]] = []
    for match in FENCE_RE.finditer(text or ""):
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict):
                out.append(parsed)
        except ValueError:
            continue
    if not out:
        first = extract_json(text or "")
        if first:
            out.append(first)
    return out
