"""Generic agent loop: LLM <-> tools until a structured JSON result appears."""
from __future__ import annotations

import json
import time
from typing import Any

from .. import config
from ..llm.jsonutil import extract_json
from ..llm.prompts import final_answer_instruction, system_prompt
from .filetools import Tool


class AgentRunner:
    """Runs one subagent invocation (a single stage) to completion.

    Shared by all systems and all LLM modes: the OpenAI client and the mock
    both receive identical message structures and tool schemas.
    """

    def __init__(self, ctx):
        self.ctx = ctx

    def run(self, agent: str, stage: str, user_content: str,
            tools: list[Tool]) -> dict[str, Any]:
        ctx = self.ctx
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt(agent, ctx.system, stage)},
            {"role": "user", "content": user_content},
        ]
        toolmap = {t.name: t for t in tools}
        schemas = [t.schema for t in tools]
        meta = {"stage": stage, "agent": agent, "system": ctx.system, "task": ctx.task,
                "repo_id": ctx.repo.get("id"), "repo_name": ctx.repo.get("name"),
                "workspace": str(ctx.workspace)}
        parse_failures = 0

        for _step in range(config.STAGE_MAX_STEPS):
            ctx.check_limits()
            result = ctx.llm.chat(messages, schemas, meta=meta)
            ctx.on_llm(result)

            if result.tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": result.content or None,
                    "tool_calls": [{"id": tc.id, "type": "function",
                                    "function": {"name": tc.name,
                                                 "arguments": json.dumps(tc.args, ensure_ascii=False)}}
                                   for tc in result.tool_calls],
                })
                for tc in result.tool_calls:
                    ctx.check_limits()
                    tool = toolmap.get(tc.name)
                    started = time.monotonic()
                    if tool is None:
                        output: Any = {"error": f"unknown tool: {tc.name}"}
                        ok = False
                    else:
                        try:
                            output = tool.handler(tc.args or {})
                            ok = True
                        except Exception as exc:  # tool errors are data for the agent
                            output = {"error": f"{type(exc).__name__}: {exc}"}
                            ok = False
                    duration = int((time.monotonic() - started) * 1000)
                    ctx.on_tool(tc.name, tc.args or {}, output, ok, duration)
                    messages.append({"role": "tool", "tool_call_id": tc.id,
                                     "content": json.dumps(output, ensure_ascii=False,
                                                           default=str)})
                continue

            parsed = extract_json(result.content or "")
            if parsed is not None:
                return parsed
            parse_failures += 1
            if parse_failures <= 1:
                messages.append({"role": "user", "content": final_answer_instruction()})
                continue
            ctx.emit("log", {"level": "warn",
                             "message": f"{agent}: could not parse structured output; "
                                        "continuing with empty result"},
                     stage, agent)
            return {}

        ctx.emit("log", {"level": "warn",
                         "message": f"{agent}: stage tool-step limit reached "
                                    f"({config.STAGE_MAX_STEPS}); continuing"},
                 stage, agent)
        return {}
